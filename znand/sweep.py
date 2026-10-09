"""Finite-trace screening plus longer-run saturation checks. No hidden oracle eviction."""
from dataclasses import asdict,replace
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import argparse,csv,hashlib,json,time,sys
from .model import Config,Simulator,workload


def job(spec):
    c=Config(**spec['config'])
    trace=workload(spec['pattern'],c.ports,spec['per_port'],spec['overlap'],c.host_mhz,c.seed)
    s=Simulator(c,trace);r=s.run()
    row={k:v for k,v in spec.items() if k!='config'}
    row.update(asdict(c));row.update({k:v for k,v in r.items() if k not in ('config','counts')})
    row.update({'count_'+k:v for k,v in r['counts'].items()})
    # Check hard throughput bound using total host-window runtime.
    cap=c.ports*c.host_bits/8*c.host_mhz/1000
    assert r['bandwidth_gbps']<=cap+1e-6
    row['host_cap_gbps']=cap
    row['lookup_or_trace_limited']=int(r['peak_outstanding']>=spec['per_port'] or c.outstanding>=spec['per_port'])
    return row


def save(rows,out):
    rows.sort(key=lambda r:r['case_id'])
    fields=sorted({k for r in rows for k in r})
    with (out/'sweep.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fields);w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in r.items()})


def execute(specs,rows,out,workers):
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(job,s):s for s in specs}
        for future in as_completed(futures):
            spec=futures[future]
            try:rows.append(future.result())
            except Exception:
                (out/'failed_case.json').write_text(json.dumps(spec,indent=2));save(rows,out);raise
            if len(rows)%40==0:save(rows,out);print(f'completed {len(rows)}',flush=True)
    save(rows,out)


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/znand/full');p.add_argument('--workers',type=int,default=4)
    p.add_argument('--per-port',type=int,default=2048);p.add_argument('--quick',action='store_true');p.add_argument('--snapshot',default='')
    a=p.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    specs=[];rows=[]
    def add(c,pattern,phase='core',overlap=0.,n=None):
        specs.append(dict(case_id=len(specs),phase=phase,pattern=pattern,overlap=overlap,per_port=n or a.per_port,config=asdict(c)))
    qds=[1,4,16,64,128,256,512,1024,2048] if not a.quick else [1,32,128]
    patterns=['A1','A2','B1','B2','B3']
    for pat in patterns:
        for ports in range(1,5):
            for stripe in (4096,16384):
                for pf in (False,True):
                    for q in qds:add(Config(ports=ports,stripe=stripe,prefetch=pf,outstanding=q),pat)
    start=time.monotonic();execute(specs,rows,out,a.workers)
    core_end=len(specs)
    # Plateau candidates: two successive QD doublings with <3% absolute rate change.
    # Recheck on longer traces below; don't label finite plateau as universal max.
    saturation=[]
    for pat in patterns:
        for ports in range(1,5):
            for stripe in (4096,16384):
                for pf in (False,True):
                    group=sorted([r for r in rows if r['pattern']==pat and r['ports']==ports and r['stripe']==stripe and r['prefetch']==pf],key=lambda r:r['outstanding'])
                    best=max(group,key=lambda r:r['bandwidth_gbps']);threshold=.95*best['bandwidth_gbps']
                    first=min(r['outstanding'] for r in group if r['bandwidth_gbps']>=threshold)
                    last=group[-3:]
                    plateau=len(last)==3 and max(r['bandwidth_gbps'] for r in last)/min(r['bandwidth_gbps'] for r in last)<1.03
                    saturation.append(dict(pattern=pat,ports=ports,stripe=stripe,prefetch=pf,observed_max_gbps=best['bandwidth_gbps'],best_qd=best['outstanding'],qd95=first,screen_plateau=plateau))
                    if not a.quick:
                        # Longer trace for all layout/port/pattern/PF groups at upper QD.
                        add(Config(ports=ports,stripe=stripe,prefetch=pf,outstanding=1024),pat,'long_check',n=a.per_port*2)
                        add(Config(ports=ports,stripe=stripe,prefetch=pf,outstanding=2048),pat,'long_check',n=a.per_port*2)
    (out/'screen_saturation.json').write_text(json.dumps(saturation,indent=2))
    # Cross-port sharing and total-load-constant experiments.
    for pat in patterns:
        for stripe in (4096,16384):
            for ports in range(1,5):
                add(Config(ports=ports,stripe=stripe,outstanding=512),pat,'total_load_fixed',n=max(128,a.per_port*4//ports))
            for pf in (False,True):
                for seed in (7,11,19):add(Config(stripe=stripe,prefetch=pf,outstanding=512,seed=seed),pat,'overlap',overlap=.5)
    for pat in ('A1','B3'):
        for stripe in (4096,16384):
            for acc in (1.,.75,.5,.25):
                for lead in (1.,5.,10.,25.):
                    for seed in (7,11,19):add(Config(stripe=stripe,prefetch=True,outstanding=512,accuracy=acc,lead_us=lead,seed=seed),pat,'accuracy_lead')
            for buf in (32,128,512):
                add(Config(stripe=stripe,prefetch=True,outstanding=512,buffer_pages=buf),pat,'buffer')
            for period in (20.,100.,1000.):
                for sync in (False,True):add(Config(stripe=stripe,outstanding=512,maintenance_period_us=period,maintenance_sync=sync),pat,'maintenance')
            for frac in (.25,.75):add(Config(stripe=stripe,outstanding=512,remap_fraction=frac),pat,'synthetic_remap')
            add(Config(stripe=stripe,outstanding=512,availability=1.),pat,'no_maintenance')
            for lim in (32,512):add(Config(stripe=stripe,outstanding=512,prefetch=True,prefetch_limit=lim),pat,'prefetch_budget')
    if a.snapshot:
        for pat in patterns:
            for stripe in (4096,16384):
                for pf in (False,True):add(Config(stripe=stripe,outstanding=512,prefetch=pf,snapshot=str(Path(a.snapshot).resolve())),pat,'mqsim_repacked')
    execute(specs[core_end:],rows,out,a.workers)
    (out/'cases.json').write_text(json.dumps(specs,indent=2))
    manifest=dict(elapsed_seconds=time.monotonic()-start,cases=len(rows),python=sys.version,per_port=a.per_port,
                  scope='finite trace synthetic zNAND sensitivity; MQSim placement only when phase=mqsim_repacked',
                  files={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in Path('znand').glob('*.py')})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest,indent=2),flush=True)
if __name__=='__main__':main()
