"""Reproducible CLI: python3 -m znand.run --config ... --out ..."""
import argparse,json,csv,hashlib
from dataclasses import asdict
from pathlib import Path
from .model import Config,Simulator
from .workloads import SCHEMA_VERSION, canonical_pattern, workload

def main():
    p=argparse.ArgumentParser();p.add_argument('--config');p.add_argument('--out',default='results/znand/single')
    p.add_argument('--pattern',default='C3',help='A1, A2, B (all 64B lines), C1, C2, C3; old B1/B2/B3 are deprecated C aliases');p.add_argument('--per-port',type=int,default=2048)
    p.add_argument('--overlap',type=float,default=0.);p.add_argument('--trace',action='store_true')
    a=p.parse_args();cfg=json.loads(Path(a.config).read_text()) if a.config else asdict(Config.die32())
    pattern=canonical_pattern(a.pattern)
    cfg['trace']=a.trace;c=Config(**cfg);inputs=workload(pattern,c.ports,a.per_port,a.overlap,c.host_mhz,c.seed)
    s=Simulator(c,inputs);r=s.run();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    r['workload_schema']=SCHEMA_VERSION;r['pattern']=pattern;r['requested_pattern']=a.pattern
    (out/'result.json').write_text(json.dumps(r,indent=2))
    fields=['port','addr','size','offer','accepted','head_since','lookup_start','lookup_end','ready','r_start','end']
    with (out/'requests.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(s.req)
    if a.trace:(out/'events.json').write_text(json.dumps(s.log,indent=2))
    print(json.dumps({k:r[k] for k in ('requests','bandwidth_gbps','mean_latency_us','p99_latency_us')},indent=2))
if __name__=='__main__':main()
