"""Placement and admission-order diagnostics, with unchanged NAND timings."""
import csv
from dataclasses import asdict
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time

SOURCE=Path(__file__).resolve().parents[2]
RESULTS=Path(os.environ.get('ZNAND_RESULTS_DIR', SOURCE/'results/znand/placement_qd_crosscheck')).resolve()
OUT=RESULTS/'crosscheck'
sys.path.insert(0,str(SOURCE));os.chdir(SOURCE)
from znand import model
from znand.model import Config, Simulator
from znand.saturation import SaturatedSimulator, time_series, summarize
from znand.read64_observation import NoPrefetchCapacitySimulator, time_series as time_series64
from znand.partial_saturation import summarize_partial

def read(p):return json.loads(Path(p).read_text())
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

CASES=[dict(name=f'{p}_{variant}',pattern=p,variant=variant) for p in ('A1','A2') for variant in ('native_layout','qd2048_fixed','qd2048_rr','qd512_rr')]
CASES += [dict(name='B_q65536_fixed',pattern='B',variant='qd65536_fixed'),dict(name='B_q65536_rr',pattern='B',variant='qd65536_rr')]

def worker(case):
    start=time.monotonic();pattern=case['pattern'];variant=case['variant']
    cfg=read(RESULTS/f'{pattern}_fifo'/'result.json')['config']
    if variant=='native_layout':cfg['snapshot']=''
    if variant.startswith('qd2048'):cfg['outstanding']=2048
    if variant.startswith('qd65536'):cfg['outstanding']=65536
    if variant.endswith('_rr'):
        # Only rotate arbitration order after the last successful acceptance.
        # All readiness, capacity, merge, lookup and response rules remain intact.
        source=textwrap.dedent(inspect.getsource(Simulator.admit))
        source=source.replace('for p in range(self.c.ports):', 'start_port=getattr(self, "admission_next_port", 0)\n    for p in [(start_port+i)%self.c.ports for i in range(self.c.ports)]:')
        source=source.replace("r['accepted']=self.now;r['merged_state']=x['state']", "r['accepted']=self.now;r['merged_state']=x['state']\n        self.admission_next_port=(p+1)%self.c.ports")
        scope=dict(vars(model));exec(source,scope);Simulator.admit=scope['admit']
        save(OUT/'rr_admission_source.json',dict(source=source,changes='Starting port rotates after successful acceptance; no change to NAND/CA, QD or buffer capacity'))
    cls=NoPrefetchCapacitySimulator if pattern=='B' else SaturatedSimulator
    sim=cls(Config(**cfg),pattern,65536*4096,2200.)
    original=sim.pump;next_time=sim.start_us+500
    def progress():
        nonlocal next_time
        if sim.now>=next_time:
            print(case['name'],round(sim.now-sim.start_us),'/2200us',flush=True);next_time=sim.now+500
        return original()
    sim.pump=progress;sim.run_for_duration()
    rows=(time_series64 if pattern=='B' else time_series)(sim,25.)
    windows=(summarize_partial if pattern=='B' else summarize)(rows,200.,500.)
    for row in rows:
        assert row['cumulative_accepted']-row['cumulative_completed']==row['outstanding_end']
        assert row['buffer_peak_mib']<=8 and row['bandwidth_gbps']<=256.000001
        for p in range(4):
            assert row[f'p{p}_outstanding_max']<=cfg['outstanding']
    result=dict(case,config=asdict(sim.c),windows=windows,counts=dict(sim.count),runtime_seconds=time.monotonic()-start,
                model_sha256=digest(SOURCE/'znand/model.py'),
                diagnostic_admission=variant.endswith('_rr'),
                admission='rotating start after last success' if variant.endswith('_rr') else 'original fixed 0,1,2,3',
                validation='in-order and conservation checked by simulator, capacity/QD/throughput checked')
    if variant=='qd2048_fixed':
        ref=read(f'results/znand/saturation/runs/{pattern}_b8_q2048.json')
        result['historical_head_or_locality_gbps']=ref['windows']['fixed']['bandwidth_gbps']
    save(OUT/case['name']/'result.json',result);save(OUT/case['name']/'timeline.json',rows)
    print('DONE',case['name'],windows['fixed']['bandwidth_gbps'],windows['fixed']['p_outstanding_mean'],flush=True)

def main():
    save(OUT/'manifest.json',dict(cases=CASES,core_hash=digest(SOURCE/'znand/model.py'),script_hash=digest(__file__),
        common='4Port,64Plane,8MiB,PF OFF,FIFO CA,unchanged tR,200-2200us fixed average',
        hypotheses=['placement alone changes supply','fixed admission permits monopolization at high QD','round-robin can separate fairness from configured QD']))
    # Independent A cases run in two processes; large B cases run sequentially.
    from concurrent.futures import ThreadPoolExecutor
    def launch(case):
        if not (OUT/case['name']/'result.json').exists():
            subprocess.run([sys.executable,'-B',__file__,case['name']],check=True)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(launch,CASES[:8]))
    for case in CASES[8:]:launch(case)
    flat=[]
    for case in CASES:
        r=read(OUT/case['name']/'result.json');w=r['windows']['fixed']
        flat.append(dict(name=case['name'],pattern=case['pattern'],gbps=w['bandwidth_gbps'],
            qd=r['config']['outstanding'],per_port_outstanding=w['p_outstanding_mean'],
            per_port_gbps=w['p_bandwidth_gbps'],buffer_mean_mib=w['buffer_mean_mib'],
            long_count=r['counts'].get('tr_long',0),sensing_count=r['counts'].get('sensing_reads',0),
            admission=r['admission']))
    save(OUT/'summary.json',flat)
    with (OUT/'summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
    print(json.dumps(flat,indent=2),flush=True)

if __name__=='__main__':
    if len(sys.argv)>1:worker(next(c for c in CASES if c['name']==sys.argv[1]))
    else:main()
