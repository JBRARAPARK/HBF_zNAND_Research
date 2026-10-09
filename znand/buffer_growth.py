"""Locality-policy buffer growth in 8MiB steps, with matched QD comparisons."""
from pathlib import Path
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor,as_completed
import csv,json,hashlib,time,argparse,math
from .reference_model_17e7d52 import Config,Simulator,workload
from .validate_results import validate


def run_case(spec):
    # Preserve the historical experiment's model and exact serialized metrics.
    c=Config(**spec['config'])
    sim=Simulator(c,workload(spec['pattern'],ports=4,per_port=8192,overlap=0.,host_mhz=c.host_mhz,seed=c.seed))
    result=sim.run()
    row={k:v for k,v in spec.items() if k!='config'}
    row.update(asdict(c));row.update({k:v for k,v in result.items() if k not in ('counts','config')})
    row.update({'count_'+k:v for k,v in result['counts'].items()})
    row['host_cap_gbps']=256.
    offer=[r['end']-r['offer'] for r in sim.req]
    row['p99_offer_latency_us']=sorted(offer)[math.ceil(len(offer)*.99)-1]
    row['port_completion_us']=[max(r['end'] for r in sim.req if r['port']==p)-30 for p in range(4)]
    row['port_mean_offer_latency_us']=[sum(r['end']-r['offer'] for r in sim.req if r['port']==p)/8192 for p in range(4)]
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=8)
    args=parser.parse_args()
    assert args.workers>0
    out=Path('results/znand/buffer_growth');out.mkdir(parents=True,exist_ok=True)
    current_hash=hashlib.sha256(Path('znand/reference_model_17e7d52.py').read_bytes()).hexdigest()
    assert current_hash==json.loads(Path('results/znand/locality/manifest.json').read_text())['model_sha256']
    old=list(csv.DictReader(Path('results/znand/locality/sweep.csv').open()))
    specs=[]
    # A1/A2: the previous high-throughput layouts, full QD comparison.
    # B1/B2/B3: hold each pattern's previous 32MiB best settings fixed.
    for mib in (32,40,48,56,64):
        for pattern,stripe in (('A1',4096),('A2',16384)):
            for q in (2048,4096,8192):
                c=Config(buffer_pages=mib*64,ports=4,stripe=stripe,prefetch=True,outstanding=q,ca_policy='locality')
                specs.append(dict(case_id=len(specs),phase='buffer_growth',pattern=pattern,buffer_mib=mib,ports=4,per_port=8192,overlap=0.,config=asdict(c)))
        for pattern,stripe in (('B1',4096),('B2',4096),('B3',16384)):
            c=Config(buffer_pages=mib*64,ports=4,stripe=stripe,prefetch=True,outstanding=8192,ca_policy='locality')
            specs.append(dict(case_id=len(specs),phase='small_read_check',pattern=pattern,buffer_mib=mib,ports=4,per_port=8192,overlap=0.,config=asdict(c)))
    (out/'cases.json').write_text(json.dumps(specs,indent=2))
    previous=[]
    if (out/'sweep.csv').exists():
        assert json.loads((out/'checkpoint.json').read_text())['model_sha256']==current_hash
        previous=list(csv.DictReader((out/'sweep.csv').open()))
    rows=[];done=set()
    for row in previous:
        cid=int(row['case_id']);spec=specs[cid]
        assert cid not in done
        assert row['pattern']==spec['pattern'] and int(row['per_port'])==spec['per_port']
        for key,value in spec['config'].items():assert str(row[key])==str(value),(cid,key)
        rows.append(row);done.add(cid)
    for spec in specs:
        if spec['case_id'] in done:continue
        matches=[r for r in old if r['pattern']==spec['pattern'] and int(r['per_port'])==spec['per_port'] and all(str(r[k])==str(v) for k,v in spec['config'].items())]
        if matches:
            r=dict(matches[0]);r.update({k:v for k,v in spec.items() if k!='config'});r['source']='reused_locality';rows.append(r);done.add(spec['case_id'])
    def save():
        keys=sorted({k for r in rows for k in r})
        with (out/'sweep.tmp').open('w',newline='') as f:
            w=csv.DictWriter(f,keys,lineterminator='\n');w.writeheader()
            for r in sorted(rows,key=lambda r:int(r['case_id'])):w.writerow({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()})
        (out/'sweep.tmp').replace(out/'sweep.csv')
        (out/'checkpoint.json').write_text(json.dumps(dict(model_sha256=current_hash,saved_rows=len(rows),planned_rows=len(specs)),indent=2))
    start=time.monotonic();save();print('planned',len(specs),'existing',len(rows),flush=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(run_case,s):s for s in specs if s['case_id'] not in done}
        for future in as_completed(futures):
            r=future.result();r['source']='new';rows.append(r);save()
            print(r['pattern'],r['buffer_mib'],r['outstanding'],round(r['bandwidth_gbps'],3),f'{len(rows)}/{len(specs)}',flush=True)
    checked=validate(out/'sweep.csv')
    (out/'manifest.json').write_text(json.dumps(dict(validated_rows=checked,new_cases=sum(r['source']=='new' for r in rows),reused_cases=sum(r['source']=='reused_locality' for r in rows),
        last_execution_seconds=time.monotonic()-start,model_sha256=current_hash,source_commit='9ad9b0c9f4c9950d375ade09ba1dc0c71c7e3ef5',
        baseline_sha256=hashlib.sha256(Path('results/znand/locality/sweep.csv').read_bytes()).hexdigest(),
        scope='4 ports, 32 planes, locality, PF ON, 8192 requests/port; buffer 32/40/48/56/64MiB. A1/A2 QD 2048/4096/8192; B1/B2/B3 QD8192. Stripe A1/B1/B2=4KiB, A2/B3=16KiB.'),indent=2))
    print('complete',checked,flush=True)
if __name__=='__main__':main()
