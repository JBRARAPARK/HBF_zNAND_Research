"""A1 latency at maximum sustained load, with continued supply past cohort end."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from znand.model import Config
from znand.saturation import SaturatedSimulator,time_series,window_summary
from znand.latency import cohort,measurements,summarize_latency

BASE=ROOT/'results/local/die64_pseudo_20261017'
OUT=ROOT/'results/local/a1_saturated_latency_20261017'
SOURCES=['znand/model.py','znand/saturation.py','znand/latency.py','scripts/measure_a1_saturated_latency.py']
def read(p):return json.loads(Path(p).read_text())
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2)+'\n')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def run(args):
    out,variant=args;target=out/variant
    assert not target.exists(),'Use a new output directory'
    began=time.monotonic()
    cfg=read(BASE/'profiles'/f'{variant}_all8_A1.json');c=Config(**cfg)
    span=read(ROOT/c.snapshot)['logical_region_span_bytes']
    sim=SaturatedSimulator(c,'A1',span,2500.).run_for_duration()
    timeline=time_series(sim,25.)
    # The extra 300us keeps full load present while the cohort completes.
    start,end=sim.start_us+200,sim.start_us+2200
    selected=cohort(sim.req,start,end)
    stats=summarize_latency(sim.req,start,end)
    window=window_summary(timeline,200,2200)
    previous=read(BASE/f'{variant}_all8_A1'/'timeline.json')
    assert timeline[:88]==previous,'Latency observer changed the existing throughput measurement'
    assert len(selected)==window['accepted_requests']
    assert stats['last_cohort_completion_us']<sim.stop_us
    assert max(sim.sequence)*4096<=span
    for r in selected:
        assert r['size']==4096
        measurements(r)
    result=dict(variant=variant,config=asdict(c),topology=c.topology(),throughput_window=window,
                latency=stats,first_half=summarize_latency(sim.req,start,start+1000),
                second_half=summarize_latency(sim.req,start+1000,end),
                warmup_latency=summarize_latency(sim.req,sim.start_us,start),
                simulated_duration_us=2500,continuous_postroll_us=300,
                latest_cohort_completion_relative_us=stats['last_cohort_completion_us']-sim.start_us,
                model_source_sha256=digest(ROOT/'znand/model.py'),
                prior_timeline_identical=True,runtime_seconds=time.monotonic()-began)
    save(target/'result.json',result);save(target/'timeline.json',timeline)
    fields=['request_id','port','addr','size','global_pc','plane','q','offer','accepted',
            'lookup_start','lookup_end','ready','r_start','end']+list(measurements(selected[0]))
    with gzip.open(target/'requests.csv.gz','wt',newline='') as f:
        w=csv.DictWriter(f,fields);w.writeheader()
        for i,r in enumerate(sim.req):
            if r['accepted'] is None or not start<=r['accepted']<end:continue
            data={k:r[k] for k in fields if k in r}
            data.update(request_id=i,global_pc=r['key'][0],plane=r['key'][1],q=r['key'][2],**measurements(r))
            w.writerow(data)
    save(target/'slowest_20.json',sorted([dict(port=r['port'],addr=r['addr'],accepted=r['accepted'],
         ready=r['ready'],r_start=r['r_start'],end=r['end'],**measurements(r)) for r in selected],
         key=lambda r:r['device_latency_us'],reverse=True)[:20])
    print('DONE',variant,window['bandwidth_gbps'],stats['all']['device_latency_us'],flush=True)
    return result

def audit(out):
    manifest=read(out/'manifest.json')
    assert all(digest(ROOT/p)==sha for p,sha in manifest['source_hashes'].items())
    assert all(digest(ROOT/p)==sha for p,sha in manifest['input_hashes'].items())
    summary=[]
    for variant in ('half_bw','full_bw'):
        result=read(out/variant/'result.json');requests=[]
        with gzip.open(out/variant/'requests.csv.gz','rt') as f:
            for row in csv.DictReader(f):
                r={k:float(row[k]) for k in ('offer','accepted','lookup_start','lookup_end','ready','r_start','end')}
                r['port']=int(row['port']);requests.append(r)
                assert all(abs(v-float(row[k]))<1e-9 for k,v in measurements(r).items())
        rebuilt=summarize_latency(requests,230,2230)
        assert rebuilt==result['latency']
        for label,pop in [('all',rebuilt['all'])]+list(rebuilt['per_port'].items()):
            summary.append(dict(variant=variant,port=label,**pop['device_latency_us']))
    save(out/'summary.json',summary)
    with (out/'summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,list(summary[0]));w.writeheader();w.writerows(summary)
    save(out/'validation.json',dict(status='passed',cases=2,request_csv_statistics_recomputed=True,
         acceptance_cohort_uncensored=True,postroll_load_continues=True,prior_throughput_timeline_identical=True,
         source_input_hashes_verified=True,latency_decomposition_checked=True))
    print('VALIDATED 2 cases, raw request statistics and uncensored cohorts',flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=OUT);p.add_argument('--validate',action='store_true')
    args=p.parse_args();out=args.out.resolve()
    if args.validate:audit(out);return
    assert not out.exists(),'Use a fresh output directory'
    paths=[BASE/'profiles'/f'{v}_all8_A1.json' for v in ('half_bw','full_bw')]
    paths+=[ROOT/read(paths[0])['snapshot']]
    paths+=[BASE/f'{v}_all8_A1'/'timeline.json' for v in ('half_bw','full_bw')]
    save(out/'manifest.json',dict(source_hashes={p:digest(ROOT/p) for p in SOURCES},
         input_hashes={str(p.relative_to(ROOT)):digest(p) for p in paths},
         accepted_window_relative_us=[200,2200],postroll_us=300,quantile_method='nearest_rank',
         definition='Device accepted AR to final Host response completion; no unloaded drain',
         assumption='Independent CA/Data per pseudo channel; no DIE shared constraint'))
    with ProcessPoolExecutor(max_workers=2) as pool:list(pool.map(run,[(out,v) for v in ('half_bw','full_bw')]))
    audit(out)

if __name__=='__main__':main()
