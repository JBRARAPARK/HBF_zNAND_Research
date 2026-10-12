"""Extend large-QD B runs to distinguish transient averages from later throughput."""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from znand.model import Config
from znand.read64_observation import NoPrefetchCapacitySimulator,time_series
from znand.partial_saturation import summarize_partial
OUT=ROOT/'results/znand/die32_high_qd'
read=lambda p:json.loads(p.read_text())
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--qd',type=int,choices=(65536,262144),required=True);a=p.parse_args()
    ref=OUT/'cases'/f'B_region_q{a.qd}'/'result.json'
    previous=read(ref);c=Config(**previous['config'])
    target=OUT/'extended'/f'B_region_q{a.qd}'
    if (target/'result.json').exists():
        raise SystemExit('Result exists; preserved')
    t=time.monotonic();sim=NoPrefetchCapacitySimulator(c,'B',65536*4096,4200.)
    pump=sim.pump;next_time=sim.start_us+1000
    def progress():
        nonlocal next_time
        if sim.now>=next_time:
            print('B tail',a.qd,round(sim.now-sim.start_us),'/4200us',flush=True);next_time=sim.now+1000
        return pump()
    sim.pump=progress;sim.run_for_duration();rows=time_series(sim,25.)
    assert len(rows)==168 and max(sim.sequence)*64<=65536*4096
    original=read(ref.with_name('timeline.json'));max_float_delta=0.
    for before,after in zip(original,rows[:88]):
        assert before.keys()==after.keys()
        for key,v in before.items():
            if isinstance(v,float):
                assert math.isclose(v,after[key],rel_tol=1e-10,abs_tol=1e-6),(key,v,after[key])
                max_float_delta=max(max_float_delta,abs(v-after[key]))
            else:assert v==after[key],key
    for row in rows:
        assert row['cumulative_accepted']-row['cumulative_completed']==row['outstanding_end']
        assert row['buffer_peak_mib']<=8 and 0<=row['bandwidth_gbps']<=256.000001
        for port in range(4):
            assert row[f'p{port}_cumulative_accepted']-row[f'p{port}_cumulative_completed']==row[f'p{port}_outstanding_end']
            assert row[f'p{port}_outstanding_max']<=c.outstanding
    early=summarize_partial(rows[:88],200.,500.)
    late=summarize_partial(rows,2200.,500.)
    result=dict(qd=a.qd,config=asdict(c),early_window_us=[200,2200],late_window_us=[2200,4200],
        early=early,late=late,runtime_seconds=time.monotonic()-t,
        validation=dict(status='passed',prefix_timeline_matches_original=True,max_float_delta=max_float_delta,
                        accounting_capacity_qd_verified=True),
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in
                      (ROOT/'znand/model.py',ROOT/'znand/read64_observation.py',Path(__file__),ref,ROOT/c.snapshot)})
    save(target/'result.json',result);save(target/'timeline.json',rows)
    print('DONE tail',a.qd,'early',early['fixed']['bandwidth_gbps'],'late',late['fixed']['bandwidth_gbps'],
          'late trend',late['second_vs_first_pct'],flush=True)

if __name__=='__main__':main()
