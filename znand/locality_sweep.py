"""Matched comparison of FIFO and bounded physical-locality CA scheduling."""
from pathlib import Path
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor,as_completed
import csv,json,hashlib,time,math
from .model import Config,Simulator,workload
from .validate_results import validate


def run_case(spec):
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
    out=Path('results/znand/locality');out.mkdir(parents=True,exist_ok=True)
    baseline_path=Path('results/znand/buffer_expansion/sweep.csv')
    baseline=list(csv.DictReader(baseline_path.open()))
    specs=[];seen=set()
    def add(pattern,mib,stripe,pf,qd,phase='core',policy='locality'):
        key=(pattern,mib,stripe,pf,qd,policy)
        if key in seen:return
        seen.add(key)
        c=Config(ports=4,buffer_pages=mib*64,stripe=stripe,prefetch=pf,outstanding=qd,ca_policy=policy)
        specs.append(dict(case_id=len(specs),phase=phase,pattern=pattern,buffer_mib=mib,ports=4,per_port=8192,overlap=0.,config=asdict(c)))
    # Full-length FIFO controls both reproduce baseline and add per-port metrics.
    for mib in (8,16,24,32):add('A2',mib,16384,True,2048,'fifo_control','fifo')
    # Main comparison holds all host workload settings fixed.
    for mib in (8,16,24,32):
        for pattern in ('A1','A2','B1','B2','B3'):
            for stripe in (4096,16384):add(pattern,mib,stripe,True,2048)
    # Also test each existing buffer/pattern's best FIFO settings, without selecting
    # new settings using locality results after the fact.
    for mib in (8,16,24,32):
        for pattern in ('A1','A2','B1','B2','B3'):
            group=[r for r in baseline if r['buffer_mib']==str(mib) and r['pattern']==pattern]
            r=max(group,key=lambda r:float(r['bandwidth_gbps']))
            add(pattern,mib,int(r['stripe']),r['prefetch']=='True',int(r['outstanding']),'prior_best')
    (out/'cases.json').write_text(json.dumps(specs,indent=2))
    def save(rows):
        fields=sorted({k for r in rows for k in r})
        with (out/'sweep.tmp').open('w',newline='') as f:
            w=csv.DictWriter(f,fields,lineterminator='\n');w.writeheader()
            for r in sorted(rows,key=lambda r:int(r['case_id'])):w.writerow({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()})
        (out/'sweep.tmp').replace(out/'sweep.csv')
    rows=[];start=time.monotonic()
    print('planned',len(specs),flush=True)
    with ProcessPoolExecutor(max_workers=8) as pool:
        futures={pool.submit(run_case,s):s for s in specs}
        for future in as_completed(futures):
            row=future.result()
            if row['ca_policy']=='fifo':
                b=next(r for r in baseline if r['pattern']=='A2' and r['buffer_mib']==str(row['buffer_mib']) and r['stripe']=='16384' and r['prefetch']=='True' and r['outstanding']=='2048')
                for key in ('bandwidth_gbps','elapsed_us','count_sensing_reads','count_tr_long','p99_latency_us','mean_offer_latency_us'):
                    assert float(b[key])==row[key],(key,b[key],row[key])
            rows.append(row);save(rows)
            print(row['case_id'],row['pattern'],row['buffer_mib'],row['ca_policy'],round(row['bandwidth_gbps'],3),f'{len(rows)}/{len(specs)}',flush=True)
    checked=validate(out/'sweep.csv')
    (out/'manifest.json').write_text(json.dumps(dict(cases=len(rows),validated_rows=checked,elapsed_seconds=time.monotonic()-start,
        model_sha256=hashlib.sha256(Path('znand/model.py').read_bytes()).hexdigest(),baseline_sha256=hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        scope='4 ports, 32 planes, 8192 requests per port, identical inputs and timing; CA scheduling only',
        policy=dict(max_bypass=8,age_us=1000),fifo_controls_reproduce_saved_results=True),indent=2))
    print('complete',checked,flush=True)

if __name__=='__main__':main()
