"""Large-QD-only extension of the validated 4-DIE performance measurement."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import measure_die32 as base

PRIOR=ROOT/'results/znand/die32_performance'
OUT=ROOT/'results/znand/die32_high_qd'
REFERENCES={p:PRIOR/'cases'/f"{p}_region_q{16384 if p=='B' else 256}"/'result.json' for p in ('A1','A2','B')}

def cases():
    result=[]
    for pattern,qds in [('A1',(4096,16384,65536)),('A2',(4096,16384,65536)),('B',(65536,131072,262144))]:
        reference=base.read(REFERENCES[pattern])
        for qd in qds:
            cfg=reference['config']|{'outstanding':qd}
            assert {k for k,v in cfg.items() if v!=reference['config'][k]}=={'outstanding'}
            result.append(dict(pattern=pattern,layout='region',qd=qd,phase='b' if pattern=='B' else 'a',
                               name=f'{pattern}_region_q{qd}',config=cfg))
    return result

base.OUT=OUT
base.cases=cases

def audit(require_all=True):
    manifest=base.read(OUT/'manifest.json')
    assert all(base.digest(ROOT/p)==h for p,h in manifest['reference_hashes'].items())
    base.audit(require_all)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=('build','a','b','all','validate','summary'),default='all')
    parser.add_argument('--case');parser.add_argument('--workers',type=int,default=1)
    args=parser.parse_args()
    if args.case:
        base.run(next(s for s in cases() if s['name']==args.case));return
    if args.phase in ('validate','summary'):
        audit(args.phase=='validate');return
    sources=base.SOURCES+['scripts/measure_die32_high_qd.py']
    manifest=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_hashes={p:base.digest(ROOT/p) for p in sources},
        snapshot_hashes={str(p.relative_to(ROOT)):base.digest(p) for p in (PRIOR/'snapshots').glob('*.json')},
        reference_hashes={str(p.relative_to(ROOT)):base.digest(p) for p in REFERENCES.values()},
        fixed_window_us=[200,2200],
        only_changed_configuration_field='outstanding',
        common='4DIE x 2 Channel x 4Plane; same region placement, 8MiB, FIFO CA, fixed admission, PF OFF, tR and 85% availability')
    if (OUT/'manifest.json').exists():
        previous=base.read(OUT/'manifest.json')
        assert {k:v for k,v in previous.items() if k!='source_commit'}=={k:v for k,v in manifest.items() if k!='source_commit'}
    else:base.save(OUT/'manifest.json',manifest)
    assert all(base.digest(ROOT/p)==h for p,h in manifest['reference_hashes'].items())
    base.save(OUT/'cases.json',cases())
    if args.phase=='build':return
    def launch(s):
        if (OUT/'cases'/s['name']/'result.json').exists():return
        subprocess.run([sys.executable,'-B',__file__,'--case',s['name']],cwd=ROOT,check=True)
    selected=[s for s in cases() if args.phase in ('all',s['phase'])]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(launch,selected))
    audit(args.phase=='all')

if __name__=='__main__':main()
