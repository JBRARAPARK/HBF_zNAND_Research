"""Staged buffer/QD, bounded PF, and Data-head experiments with frozen checks."""
import argparse
import csv
import hashlib
import json
import math
import multiprocessing
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from .model import Config, workload
from .scheduling_probe import SchedulingProbe
from .diagnostics import merge_intervals, intersection_duration
from .validate_results import validate

SOURCE_FILES = ('znand/model.py', 'znand/scheduling_probe.py', 'znand/scheduling_sweep.py')
RULES = dict(stage_a='Max throughput with offer p99 <= 1.05x the original profile; tie: lower p99, buffer, QD.',
             stage_b='Per-pattern PF budget maximizing geometric throughput across accuracy 1/.75/.5; all ratios >= .98 and p99 ratios <= 1.05. Zero budget is included.',
             stage_c='Max throughput among CA head OFF/ON x Data head OFF/ON, p99 <= 1.05x the stage-B baseline. Tie prefers the baseline, then simpler policy.',
             checks='Freeze candidate before long traces, seeds, remap, port counts, B patterns and 64Plane. Report paired regressions; do not retune on checks.')


def original(pattern):
    return asdict(Config(**json.loads(Path(f'results/znand/head_locality/profiles/{pattern}.json').read_text())))


def run_case(spec):
    started = time.monotonic()
    c = Config(**spec['config'])
    sim = SchedulingProbe(c, workload(spec['pattern'], ports=c.ports, per_port=spec['per_port'],
                                     overlap=spec['overlap'], host_mhz=c.host_mhz, seed=c.seed))
    result = sim.run()
    row = {k:v for k,v in spec.items() if k != 'config'}
    row.update(asdict(c))
    row.update({k:v for k,v in result.items() if k not in ('counts', 'config')})
    row.update({'count_'+k:v for k,v in result['counts'].items()})
    row.update(sim.diagnostics())
    row['host_cap_gbps'] = c.ports*c.host_bits/8*c.host_mhz/1000
    quant99 = lambda a:sorted(a)[math.ceil(len(a)*.99)-1]
    row['p99_offer_latency_us'] = quant99([r['end']-r['offer'] for r in sim.req])
    heads = [max(0., r['ready']-max(r['head_since'], r['lookup_end'])) for r in sim.req]
    row['p99_head_data_wait_us'] = quant99(heads)
    row['mean_head_data_wait_us'] = sum(heads)/len(heads)
    completion, p99, hol = [], [], []
    for port in range(c.ports):
        requests = [r for r in sim.req if r['port'] == port]
        assert [r['end'] for r in requests] == sorted(r['end'] for r in requests)
        previous = 0.
        for r in requests:
            assert r['head_since'] == max(previous, r['accepted'])
            assert r['r_start'] >= previous
            previous = r['end']
        completion.append(max(r['end'] for r in requests)-min(r['offer'] for r in requests))
        p99.append(quant99([r['end']-r['offer'] for r in requests]))
        missing = merge_intervals((max(r['head_since'], r['lookup_end']), r['ready']) for r in requests)
        ready = merge_intervals((max(r['ready'], r['lookup_end']), r['r_start']) for r in requests)
        hol.append(intersection_duration(missing, ready)/result['elapsed_us']*100)
    row.update(port_completion_us=completion, port_p99_offer_us=p99,
               port_idle_while_later_ready_pct=hol, mean_port_idle_while_later_ready_pct=sum(hol)/c.ports,
               slowest_port_p99_offer_us=max(p99), runtime_seconds=time.monotonic()-started)
    # A final CA may not have reached ca_done at the Host measurement endpoint.
    assert 0 <= row['diag_long_ca_choices']-result['counts'].get('tr_long', 0) <= c.channels
    return row


def spec(name, stage, pattern, config, per_port=8192, pair='', variant='', overlap=0.):
    return dict(name=name, stage=stage, pattern=pattern, config=config, per_port=per_port,
                overlap=overlap, buffer_mib=config['buffer_pages']/64, pair=pair, variant=variant)


def stage_a():
    return [spec(f'A_{p}_b{m}_q{q}', 'A', p, dict(original(p), buffer_pages=m*64, outstanding=q))
            for p in ('A1','A2') for m in (32,40,48) for q in (1024,2048,4096)]


def stage_b(chosen):
    return [spec(f'B_{p}_a{accuracy}_pf{budget}', 'B', p, dict(chosen[p], accuracy=accuracy, pf_ahead_limit=budget))
            for p in ('A1','A2') for accuracy in (1.,.75,.5) for budget in (0,1,2)]


def stage_c(chosen):
    return [spec(f'C_{p}_ca{ca}_data{data}', 'C', p,
                 dict(chosen[p], ca_policy=ca, head_wait_us=48.64, data_policy=data))
            for p in ('A1','A2') for ca in ('locality','head_locality') for data in ('ready','head')]


def check_specs(chosen):
    specs = []
    for p in ('A1','A2'):
        scenarios = [('long', {}, 16384, 0.)]
        scenarios += [(f'seed{s}', {'seed':s}, 8192, 0.) for s in (17,29)]
        scenarios += [(f'remap{x}', {'remap_fraction':x}, 8192, 0.) for x in (.25,.75)]
        scenarios += [(f'ports{n}', {'ports':n}, 8192, 0.) for n in (1,2,3)]
        scenarios += [('planes64', {'planes':16}, 8192, 0.)]
        for label, changes, length, overlap in scenarios:
            for variant, cfg in [('baseline',original(p)),('candidate',chosen[p])]:
                specs.append(spec(f'check_{p}_{label}_{variant}', 'checks', p, dict(cfg,**changes),
                                  length, f'{p}_{label}', variant, overlap))
    # Transfer only the new resource/PF/Data choices; preserve B's locality CA.
    for p in ('B1','B2','B3'):
        source = chosen['A2' if p == 'B3' else 'A1']
        candidate = dict(original(p), **{k:source[k] for k in
                         ('buffer_pages','outstanding','pf_ahead_limit','pf_head_wait_us',
                          'data_policy','data_head_wait_us','data_age_us')})
        for variant, cfg in [('baseline',original(p)),('candidate',candidate)]:
            specs.append(spec(f'check_{p}_transfer_{variant}', 'checks', p, cfg, pair=f'{p}_transfer', variant=variant))
    return specs


def select_a(rows, cases):
    configs, audit = {}, {}
    for p in ('A1','A2'):
        options = [r for r in rows if r['stage']=='A' and r['pattern']==p]
        base = next(r for r in options if r['buffer_pages']==2048 and r['outstanding']==2048)
        allowed = [r for r in options if r['p99_offer_latency_us'] <= base['p99_offer_latency_us']*1.05]
        selected = max(allowed, key=lambda r:(r['bandwidth_gbps'], -r['p99_offer_latency_us'], -r['buffer_pages'], -r['outstanding']))
        configs[p] = cases[selected['name']]['config']
        audit[p] = dict(selected=selected['name'], baseline=base['name'], eligible=[r['name'] for r in allowed])
    return configs, audit


def select_b(rows, cases):
    configs, audit = {}, {}
    for p in ('A1','A2'):
        options = [r for r in rows if r['stage']=='B' and r['pattern']==p]
        scores=[]
        for budget in (0,1,2):
            ratios=[];tails=[]
            for accuracy in (1.,.75,.5):
                base=next(r for r in options if r['accuracy']==accuracy and r['pf_ahead_limit']==0)
                cur=next(r for r in options if r['accuracy']==accuracy and r['pf_ahead_limit']==budget)
                ratios.append(cur['bandwidth_gbps']/base['bandwidth_gbps'])
                tails.append(cur['p99_offer_latency_us']/base['p99_offer_latency_us'])
            scores.append(dict(budget=budget, geometric_ratio=math.prod(ratios)**(1/3),
                               min_ratio=min(ratios), max_p99_ratio=max(tails),
                               allowed=min(ratios)>=.98 and max(tails)<=1.05))
        best=max((s for s in scores if s['allowed']),key=lambda s:(s['geometric_ratio'],-s['budget']))
        selected=next(r for r in options if r['accuracy']==1. and r['pf_ahead_limit']==best['budget'])
        configs[p]=cases[selected['name']]['config'];audit[p]=dict(selected=selected['name'],scores=scores)
    return configs,audit


def select_c(rows, cases, baseline):
    configs,audit={},{}
    for p in ('A1','A2'):
        options=[r for r in rows if r['stage']=='C' and r['pattern']==p]
        base=next(r for r in options if r['ca_policy']==baseline[p]['ca_policy'] and r['data_policy']=='ready')
        allowed=[r for r in options if r['p99_offer_latency_us']<=base['p99_offer_latency_us']*1.05]
        selected=max(allowed,key=lambda r:(r['bandwidth_gbps'],r['name']==base['name'],r['data_policy']=='ready',r['ca_policy']=='locality'))
        configs[p]=cases[selected['name']]['config']
        audit[p]=dict(selected=selected['name'],baseline=base['name'],eligible=[r['name'] for r in allowed])
    return configs,audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',default='results/znand/scheduling_next')
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--through',choices=('A','B','C','checks'),default='checks')
    args=parser.parse_args();assert args.workers>0
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    hashes={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in SOURCE_FILES}
    metadata=dict(hashes=hashes, rules=RULES,
                  source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
    if (out/'checkpoint.json').exists():
        prior=json.loads((out/'checkpoint.json').read_text());assert prior['hashes']==hashes and prior['rules']==RULES
        metadata=prior
    else:(out/'checkpoint.json').write_text(json.dumps(metadata,indent=2)+'\n')
    rows=json.loads((out/'rows.json').read_text()) if (out/'rows.json').exists() else []
    cases=json.loads((out/'cases.json').read_text()) if (out/'cases.json').exists() else []
    selections={}
    def save():
        (out/'rows.tmp').write_text(json.dumps(rows,indent=2)+'\n');(out/'rows.tmp').replace(out/'rows.json')
        (out/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
        if rows:
            fields=sorted({k for r in rows for k in r})
            with (out/'sweep.tmp').open('w',newline='') as f:
                writer=csv.DictWriter(f,fields,lineterminator='\n');writer.writeheader()
                for r in sorted(rows,key=lambda r:r['case_id']):
                    writer.writerow({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()})
            (out/'sweep.tmp').replace(out/'sweep.csv')
    previous=list(csv.DictReader(Path('results/znand/head_locality/sweep.csv').open()))
    def check_control(r):
        if r['stage']!='A' or r['buffer_pages']!=2048 or r['outstanding']!=2048:return
        prior=next(x for x in previous if x['pattern']==r['pattern'] and x['per_port']=='8192'
                   and x['ca_policy']==r['ca_policy'] and x['locality_max_bypass']=='32'
                   and float(x['head_wait_us'])==r['head_wait_us'])
        for k,v in prior.items():
            if k.startswith(('count_','mean_','p99_','p95_','channel_','port_')) or k in ('bandwidth_gbps','elapsed_us','requests','host_bytes','buffer_peak_pages','peak_outstanding'):
                if v.startswith('['):assert json.loads(v)==r[k],(r['name'],k)
                else:assert float(v or 0)==float(r.get(k) or 0),(r['name'],k,v,r.get(k))
    def execute(batch):
        lookup={s['name']:s for s in cases}
        for s in batch:
            if s['name'] in lookup:
                s['case_id']=lookup[s['name']]['case_id'];assert s==lookup[s['name']]
            else:s['case_id']=len(cases);cases.append(s)
        lookup={s['name']:s for s in cases}
        for r in rows:
            s=lookup[r['name']]
            assert all(r[k]==v for k,v in s['config'].items())
            assert all(r[k]==v for k,v in s.items() if k!='config')
        save();done={r['name'] for r in rows}
        with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
            futures={pool.submit(run_case,s):s for s in batch if s['name'] not in done}
            for f in as_completed(futures):
                r=f.result();check_control(r);rows.append(r);save()
                print(r['name'],round(r['bandwidth_gbps'],4),'GB/s',round(r['p99_offer_latency_us'],2),'p99',f'{len(rows)}/{len(cases)}',flush=True)
        assert validate(out/'sweep.csv')==len(rows)
    def freeze(label,configs,audit):
        document=dict(configs=configs,audit=audit)
        path=out/f'selection_{label}.json'
        if path.exists():assert json.loads(path.read_text())==document
        else:path.write_text(json.dumps(document,indent=2)+'\n')
        selections[label]=document
        print('selected',label,json.dumps(audit),flush=True)
    started=time.monotonic()
    execute(stage_a());a,audit=select_a(rows,{s['name']:s for s in cases});freeze('A',a,audit)
    if args.through in ('B','C','checks'):
        execute(stage_b(a));b,audit=select_b(rows,{s['name']:s for s in cases});freeze('B',b,audit)
    if args.through in ('C','checks'):
        execute(stage_c(b));c,audit=select_c(rows,{s['name']:s for s in cases},b);freeze('C',c,audit)
        profiles=out/'profiles';profiles.mkdir(exist_ok=True)
        for p in ('A1','A2'):
            (profiles/f'candidate_{p}.json').write_text(json.dumps(c[p],indent=2)+'\n')
            (profiles/f'baseline_{p}.json').write_text(json.dumps(original(p),indent=2)+'\n')
    if args.through=='checks':execute(check_specs(c))
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    manifest=dict(metadata,validated_rows=len(rows),phase_counts=dict((s,sum(r['stage']==s for r in rows)) for s in ('A','B','C','checks')),
                  complete_through=args.through,last_execution_seconds=time.monotonic()-started,
                  reference_controls_match=True,geometry='4 channels; planes is per channel; strict per-port in-order',
                  occupancy='Exact time integral over first Host offer to last Host return; ready includes returning payload and unused PF.',
                  long_diagnostics='Offline next-page inspection after selection; not used for scheduling. Final in-flight CA choices may exceed classified tr_long by up to channels.')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('complete',len(rows),flush=True)


if __name__=='__main__':main()
