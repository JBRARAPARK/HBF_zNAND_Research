"""Matched four-port buffer sweep; preserve the validated model and baseline."""
from pathlib import Path
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv, hashlib, json, time
from .reference_model_2b1a831 import Config, Simulator, workload
from .validate_results import validate


def job(spec):
    c=Config(**spec['config'])
    result=Simulator(c,workload(spec['pattern'],c.ports,spec['per_port'],spec['overlap'],c.host_mhz,c.seed)).run()
    row={k:v for k,v in spec.items() if k!='config'}
    row.update(asdict(c))
    row.update({k:v for k,v in result.items() if k not in ('config','counts')})
    row.update({'count_'+k:v for k,v in result['counts'].items()})
    row['host_cap_gbps']=c.ports*c.host_bits/8*c.host_mhz/1000
    row['lookup_or_trace_limited']=int(result['peak_outstanding']>=spec['per_port'] or c.outstanding>=spec['per_port'])
    assert result['bandwidth_gbps']<=row['host_cap_gbps']+1e-6
    return row


def main():
    out=Path('results/znand/buffer_expansion');out.mkdir(parents=True,exist_ok=True)
    model_hash=hashlib.sha256(Path(__file__).with_name('reference_model_2b1a831.py').read_bytes()).hexdigest()
    assert json.loads(Path('results/znand/extended/manifest.json').read_text())['model_sha256']==model_hash
    baseline=[r for r in csv.DictReader(Path('results/znand/extended/sweep.csv').open()) if r['ports']=='4']
    assert len(baseline)==60
    specs=[]
    for mib in (16,24,32):
        for pat in ('A1','A2','B1','B2','B3'):
            for stripe in (4096,16384):
                for pf in (False,True):
                    for q in (2048,4096,8192):
                        c=Config(ports=4,buffer_pages=mib*64,stripe=stripe,prefetch=pf,outstanding=q)
                        specs.append(dict(case_id=len(specs),phase='buffer_expansion',pattern=pat,overlap=0.,per_port=8192,config=asdict(c)))
    (out/'cases.json').write_text(json.dumps(specs,indent=2))
    rows=[]
    if (out/'sweep.csv').exists():
        rows=[r for r in csv.DictReader((out/'sweep.csv').open()) if r['source']=='new']
    done={int(r['case_id']) for r in rows}
    assert len(done)==len(rows), 'Duplicate checkpoint cases'
    expected={s['case_id']:s for s in specs}
    for row in rows:
        spec=expected[int(row['case_id'])]
        for key,value in spec['config'].items():
            assert str(row[key])==str(value), (row['case_id'],key)
        assert int(row['per_port'])==spec['per_port'] and row['pattern']==spec['pattern']
    if len(done)==len(specs):
        print('Existing complete results validated:',validate(out/'sweep.csv'))
        return
    start=time.monotonic()
    def save():
        combined=[]
        for r in baseline:
            combined.append(dict(r,source='extended_8MiB',buffer_mib=8))
        for r in sorted(rows,key=lambda r:int(r['case_id'])):
            combined.append(dict(r,source='new',buffer_mib=int(r['buffer_pages'])//64))
        fields=sorted({k for r in combined for k in r})
        with (out/'sweep.csv.tmp').open('w',newline='') as f:
            w=csv.DictWriter(f,fields,lineterminator='\n');w.writeheader()
            for r in combined:w.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in r.items()})
        (out/'sweep.csv.tmp').replace(out/'sweep.csv')
    with ProcessPoolExecutor(max_workers=8) as pool:
        fs={pool.submit(job,s):s for s in specs if s['case_id'] not in done}
        for future in as_completed(fs):
            rows.append(future.result())
            save()
            if len(rows)%10==0:
                print(f'completed {len(rows)}/{len(specs)}, elapsed {time.monotonic()-start:.1f}s',flush=True)
    save()
    checked=validate(out/'sweep.csv')
    (out/'manifest.json').write_text(json.dumps(dict(new_cases=len(rows),reused_baseline_cases=len(baseline),validated_rows=checked,
        last_execution_elapsed_seconds=time.monotonic()-start,reused_checkpoint_cases=len(done),model_sha256=model_hash,
        baseline_sha256=hashlib.sha256(Path('results/znand/extended/sweep.csv').read_bytes()).hexdigest(),
        scope='4 ports, 8192 requests/port, same seed and timing; only buffer and outstanding swept'),indent=2))
    print('validated',checked,flush=True)

if __name__=='__main__':main()
