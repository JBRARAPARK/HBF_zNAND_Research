"""Check optimized PF-OFF 64B observation against the reference on eight channels."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from znand.model import Config
from znand.workloads import ContinuousRead64Simulator
from znand.read64_observation import NoPrefetchCapacitySimulator,time_series
from znand.saturation import SaturatedSimulator, time_series as a_series
from measure_die32 import ObservedA

c=Config.die32(outstanding=128,buffer_pages=8)
checks=[]
for pattern in ('A1','A2'):
    a=SaturatedSimulator(c,pattern,4096*65536,120.).run_for_duration()
    b=ObservedA(c,pattern,4096*65536,120.).run_for_duration()
    assert a.req==b.req and a.count==b.count and a.reservations==b.reservations
    assert a_series(a,10.)==a_series(b,10.)
    checks.append(dict(pattern=pattern,status='passed',requests=len(a.req),
                       observation_hooks_preserve_requests_counters_buffer_and_timelines=True))
for pattern in ('B','C1','C2'):
    a=ContinuousRead64Simulator(c,pattern,4096*65536,120.).run_for_duration()
    b=NoPrefetchCapacitySimulator(c,pattern,4096*65536,120.).run_for_duration()
    assert a.req==b.req and a.count==b.count
    assert a.reservations==b.reservations
    assert a.sensing==b.sensing and a.nand_transfers==b.nand_transfers
    assert time_series(a,10.)==time_series(b,10.)
    checks.append(dict(pattern=pattern,status='passed',requests=len(a.req),
                       timestamps_counters_buffer_events_nand_events_and_timelines_identical=True))
out=ROOT/'results/znand/die32_performance/observer_validation.json'
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(dict(status='passed',config=asdict(c),cases=checks,
    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    note='Equivalence regression on short buffer-constrained traces; not a hardware validation'),indent=2)+'\n')
print('Passed 5 reference/instrumented observer comparisons')
