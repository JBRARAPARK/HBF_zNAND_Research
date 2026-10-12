"""Matched current-model round-robin measurements; fixed results remain historical."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import measure_die32 as base
from znand.model import Simulator
OUT=ROOT/'results/znand/die32_round_robin'

def references():
    paths=[]
    for pattern,qds in [('A1',(256,65536)),('A2',(256,65536)),('B',(16384,65536,262144))]:
        for qd in qds:
            folder='die32_performance' if qd in (256,16384) else 'die32_high_qd'
            paths.append(ROOT/'results/znand'/folder/'cases'/f'{pattern}_region_q{qd}'/'result.json')
    return paths

def cases():
    result=[]
    for path in references():
        r=base.read(path)
        result.append({k:r[k] for k in ('pattern','layout','qd','phase','name','config')} |
            dict(admission_policy=Simulator.admission_policy,reference=str(path.relative_to(ROOT))))
    return result

base.OUT=OUT
base.cases=cases

def audit():
    manifest=base.read(OUT/'manifest.json')
    assert all(base.digest(ROOT/p)==h for p,h in manifest['reference_hashes'].items())
    for spec in cases():
        assert spec['admission_policy']=='round_robin'
        r=base.read(OUT/'cases'/spec['name']/'result.json')
        assert r['admission_policy']=='round_robin'
        assert r['config']==base.read(ROOT/spec['reference'])['config']
    base.audit()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case');parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--validate',action='store_true');args=parser.parse_args()
    if args.case:
        base.run(next(s for s in cases() if s['name']==args.case));return
    if args.validate:audit();return
    sources=base.SOURCES+['scripts/measure_die32_round_robin.py']
    manifest=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_hashes={p:base.digest(ROOT/p) for p in sources},
        snapshot_hashes={s['config']['snapshot']:base.digest(ROOT/s['config']['snapshot']) for s in cases()},
        reference_hashes={str(p.relative_to(ROOT)):base.digest(p) for p in references()},
        fixed_window_us=[200,2200],admission_policy='round_robin',
        common='Only production admission changed; identical configuration, region snapshots and workloads to fixed-admission references')
    if (OUT/'manifest.json').exists():
        previous=base.read(OUT/'manifest.json')
        assert {k:v for k,v in previous.items() if k!='source_commit'}=={k:v for k,v in manifest.items() if k!='source_commit'}
    else:base.save(OUT/'manifest.json',manifest)
    base.save(OUT/'cases.json',cases())
    def launch(s):
        if (OUT/'cases'/s['name']/'result.json').exists():return
        subprocess.run([sys.executable,'-B',__file__,'--case',s['name']],cwd=ROOT,check=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(launch,cases()))
    audit()

if __name__=='__main__':main()
