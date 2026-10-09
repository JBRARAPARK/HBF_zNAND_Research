"""Compare complete PF ON/OFF at fixed Host QD; reuse exact current-model controls."""
import argparse
import csv
import hashlib
import json
import math
import multiprocessing
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .scheduling_sweep import SOURCE_FILES, original, run_case, spec
from .validate_results import validate

ROOT = Path('results/znand/pf_qd')
REFERENCE = Path('results/znand/scheduling_next')
QDS = (128, 1024, 2048, 4096, 8192)
FILES = (*SOURCE_FILES, 'znand/pf_qd_sweep.py')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())


def cases():
    result=[]
    for pattern in ('A1','A2'):
        base=original(pattern)
        conditions=[('qd',q,8,8192) for q in QDS]
        conditions += [('long',2048,8,16384),('planes64',2048,16,8192)]
        for stage,qd,planes,length in conditions:
            pair=f'{pattern}_{stage}_q{qd}'
            for pf in (False,True):
                c=dict(base,prefetch=pf,outstanding=qd,planes=planes,pf_ahead_limit=0,data_policy='ready')
                s=spec(f'{pair}_pf{int(pf)}',stage,pattern,c,length,pair,'on' if pf else 'off')
                s['case_id']=len(result);result.append(s)
    return result


def compatible(row,s):
    return all(row.get(k)==v for k,v in s['config'].items()) and all(
        row.get(k)==s[k] for k in ('pattern','per_port','overlap'))


def annotate(row,source,source_case):
    # Integral of accepted-to-last-return occupancy, averaged over all ports.
    row['mean_outstanding_per_port']=row['requests']*row['mean_latency_us']/row['elapsed_us']/row['ports']
    row.update(source=source,source_case=source_case)
    return row


def save(out,rows):
    rows.sort(key=lambda r:r['case_id'])
    (out/'rows.tmp').write_text(json.dumps(rows,indent=2)+'\n');(out/'rows.tmp').replace(out/'rows.json')
    fields=sorted({k for r in rows for k in r})
    if not fields:return
    with (out/'sweep.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fields,lineterminator='\n');writer.writeheader()
        writer.writerows({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)


def audit(out):
    manifest=read(out/'manifest.json');rows=read(out/'rows.json');specs=read(out/'cases.json')
    assert all(digest(p)==h for p,h in manifest['hashes'].items())
    assert digest(REFERENCE/'rows.json')==manifest['reference_rows_sha256']
    assert specs==cases() and len(rows)==len(specs)==28
    assert len({r['case_id'] for r in rows})==28
    assert validate(out/'sweep.csv')==28
    serialized={r['name']:r for r in csv.DictReader((out/'sweep.csv').open())}
    historical={r['name']:r for r in read(REFERENCE/'rows.json')}
    for r in rows:
        s=specs[r['case_id']];assert compatible(r,s)
        assert all(r[k]==v for k,v in s.items() if k!='config')
        for k,v in r.items():
            assert serialized[r['name']][k]==(json.dumps(v) if isinstance(v,(dict,list)) else str(v)),(r['name'],k)
        assert 0<r['mean_outstanding_per_port']<=r['peak_outstanding']<=r['outstanding']
        assert math.isclose(r['mean_outstanding_per_port'],r['per_port']*r['mean_latency_us']/r['elapsed_us'])
        if not r['prefetch']:
            assert all(v==0 for k,v in r.items() if k.startswith('count_prefetch_'))
            assert r['leftover_prefetch_pages']==0
            assert r['inclusive_prefetch_gbps']==r['bandwidth_gbps']
        if r['source']=='reused':
            previous=historical[r['source_case']]
            for k,v in previous.items():
                if k not in ('case_id','name','stage','pair','variant'):assert r[k]==v,(r['name'],k)
        components=[v for k,v in r.items() if k.startswith('diag_buffer_mean_') and k!='diag_buffer_mean_total_mib']
        assert math.isclose(sum(components),r['diag_buffer_mean_total_mib'],abs_tol=1e-9)
    for pair in {r['pair'] for r in rows}:
        a,b=[r for r in rows if r['pair']==pair]
        assert a['prefetch'] is False and b['prefetch'] is True
        assert all(a[k]==b[k] for k in specs[a['case_id']]['config'] if k!='prefetch')
    counts={source:sum(r['source']==source for r in rows) for source in ('new','reused')}
    assert counts==dict(new=18,reused=10)
    assert counts==manifest['runs']
    result=dict(status='passed',validated_rows=28,**counts,complete_pf_off_verified=True,
                same_condition_pairs=14,reused_metrics_exact=True,csv_json_agree=True,
                source_hashes_match=True,sweep_sha256=digest(out/'sweep.csv'))
    (out/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT)
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args();assert args.workers>0
    if args.validate_only:print(json.dumps(audit(args.out)));return
    out=args.out;out.mkdir(parents=True,exist_ok=True)
    reference_manifest=read(REFERENCE/'manifest.json')
    assert all(digest(p)==h for p,h in reference_manifest['hashes'].items())
    metadata=dict(hashes={p:digest(p) for p in FILES},reference_rows_sha256=digest(REFERENCE/'rows.json'),
                  source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  scope='Only prefetch Boolean differs inside each pair. No dynamic PF gating or model change.')
    if (out/'checkpoint.json').exists():
        previous=read(out/'checkpoint.json')
        assert previous['hashes']==metadata['hashes'] and previous['reference_rows_sha256']==metadata['reference_rows_sha256']
        metadata=previous
    else:(out/'checkpoint.json').write_text(json.dumps(metadata,indent=2)+'\n')
    specs=cases()
    if (out/'cases.json').exists():assert read(out/'cases.json')==specs
    (out/'cases.json').write_text(json.dumps(specs,indent=2)+'\n')
    rows=read(out/'rows.json') if (out/'rows.json').exists() else []
    done={r['name'] for r in rows};reference=read(REFERENCE/'rows.json')
    for s in specs:
        if s['name'] in done:continue
        matches=[r for r in reference if compatible(r,s)]
        if not matches:continue
        prev=matches[0];r=dict(prev);r.update({k:v for k,v in s.items() if k!='config'})
        rows.append(annotate(r,'reused',prev['name']));done.add(s['name'])
    save(out,rows)
    print('exact reused controls',len(rows),flush=True)
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(run_case,s) for s in specs if s['name'] not in done]):
            r=future.result();rows.append(annotate(r,'new',r['name']));save(out,rows)
            print(r['name'],round(r['bandwidth_gbps'],4),'GB/s',round(r['p99_offer_latency_us'],2),'p99',f'{len(rows)}/28',flush=True)
    assert all(digest(p)==h for p,h in metadata['hashes'].items())
    (out/'manifest.json').write_text(json.dumps(dict(metadata,validated_rows=len(rows),
        runs={source:sum(r['source']==source for r in rows) for source in ('new','reused')}),indent=2)+'\n')
    print(json.dumps(audit(out)),flush=True)


if __name__=='__main__':main()
