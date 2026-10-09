"""Extend upper-QD checks on longer finite workloads until buffer-limited plateau."""
from pathlib import Path
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor,as_completed
import csv,json,time,hashlib
from .model import Config
from .sweep import job

def main():
    out=Path('results/znand/extended');out.mkdir(parents=True,exist_ok=True)
    specs=[]
    # Same-length comparisons at 2K,4K,8K QD; 8192 requests per port.
    for pat in ('A1','A2','B1','B2','B3'):
        for p in range(1,5):
            for stripe in (4096,16384):
                for pf in (False,True):
                    for q in (2048,4096,8192):
                        c=Config(ports=p,stripe=stripe,prefetch=pf,outstanding=q)
                        specs.append(dict(case_id=len(specs),phase='extended',pattern=pat,overlap=0.,per_port=8192,config=asdict(c)))
    rows=[];start=time.monotonic()
    with ProcessPoolExecutor(max_workers=4) as pool:
        fs={pool.submit(job,s):s for s in specs}
        for f in as_completed(fs):
            rows.append(f.result())
            if len(rows)%20==0:print('extended',len(rows),'/',len(specs),flush=True)
    rows.sort(key=lambda r:r['case_id'])
    fields=sorted({k for r in rows for k in r})
    with (out/'sweep.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fields);w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in r.items()})
    summary=[]
    for pat in ('A1','A2','B1','B2','B3'):
        for p in range(1,5):
            for stripe in (4096,16384):
                for pf in (False,True):
                    g=[r for r in rows if (r['pattern'],r['ports'],r['stripe'],r['prefetch'])==(pat,p,stripe,pf)]
                    last=[r for r in g if r['outstanding']>=4096]
                    delta=(max(r['bandwidth_gbps'] for r in last)/min(r['bandwidth_gbps'] for r in last)-1)*100
                    best=max(g,key=lambda r:r['bandwidth_gbps'])
                    summary.append(dict(pattern=pat,ports=p,stripe=stripe,prefetch=pf,upper_qd_change_pct=delta,
                                        plateau=delta<3,best_bandwidth_gbps=best['bandwidth_gbps'],best_qd=best['outstanding'],
                                        observed_peak_outstanding=best['peak_outstanding'],p99_latency_us=best['p99_latency_us']))
    with (out/'saturation.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,list(summary[0]));w.writeheader();w.writerows(summary)
    (out/'cases.json').write_text(json.dumps(specs,indent=2))
    (out/'manifest.json').write_text(json.dumps(dict(cases=len(rows),elapsed_seconds=time.monotonic()-start,
        model_sha256=hashlib.sha256(Path('znand/model.py').read_bytes()).hexdigest()),indent=2))
    print('plateau',sum(r['plateau'] for r in summary),'/',len(summary),flush=True)
if __name__=='__main__':main()
