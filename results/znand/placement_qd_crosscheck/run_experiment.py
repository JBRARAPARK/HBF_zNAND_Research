"""Paired FIFO ablation of the existing zNAND maximum-throughput profiles.

Run with Python -B; original sources, profiles and results are read-only inputs.
"""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from dataclasses import asdict

SOURCE = Path('/Users/bagjunbeom/Documents/Codex/2026-10-07/notion-plugin-notion-openai-curated-remote/outputs/HBF_zNAND_Research')
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE))
os.chdir(SOURCE)

from znand.model import Config
from znand.saturation import SaturatedSimulator, time_series, summarize
from znand.read64_observation import NoPrefetchCapacitySimulator, time_series as time_series64
from znand.partial_saturation import summarize_partial


def read(p):
    return json.loads(Path(p).read_text())


def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2) + '\n')


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def reference(pattern):
    if pattern == 'B':
        return Path('results/znand/b_sequential/cases/B_b8_q32768/result.json')
    return Path(f'results/znand/saturation/runs/{pattern}_b8_q512.json')


def worker(pattern, mode):
    start = time.monotonic()
    ref = read(reference(pattern))
    cfg = dict(ref['config'])
    if mode == 'fifo':
        cfg['ca_policy'] = 'fifo'
    changed = {k for k in cfg if cfg[k] != ref['config'][k]}
    assert changed == ({'ca_policy'} if mode == 'fifo' else set())
    span = read(cfg['snapshot']).get('logical_region_span_bytes', 65536 * 4096)
    cls = NoPrefetchCapacitySimulator if pattern == 'B' else SaturatedSimulator
    sim = cls(Config(**cfg), pattern, span, 2200.)
    ca_original = sim.ca_candidates
    actual_bypasses = 0
    ca_issued = 0

    def observed_ca(waiting):
        nonlocal actual_bypasses, ca_issued
        best, decisions = ca_original(waiting)
        for _, item in best.values():
            plane_items = [x for x in waiting if x['key'][:2] == item['key'][:2]]
            demand = [x for x in plane_items if sim.demand(x)]
            oldest = min(demand or plane_items, key=lambda x: x['seq'])
            bypassed = item is not oldest
            if mode == 'fifo':
                assert not bypassed, 'FIFO issued a younger same-plane job'
            actual_bypasses += int(bypassed)
            ca_issued += 1
        return best, decisions

    sim.ca_candidates = observed_ca
    pump_original = sim.pump
    next_progress = sim.start_us + 250.

    def progress():
        nonlocal next_progress
        if sim.now >= next_progress:
            print(f'{pattern}/{mode}: {sim.now-sim.start_us:.1f}/2200 us, {sim.finished:,} completed', flush=True)
            next_progress = sim.now + 250.
        return pump_original()

    sim.pump = progress
    sim.run_for_duration()
    timeline = (time_series64 if pattern == 'B' else time_series)(sim, 25.)
    windows = (summarize_partial if pattern == 'B' else summarize)(timeline, 200., 500.)
    assert len(timeline) == 88
    for row in timeline:
        assert row['cumulative_accepted'] - row['cumulative_completed'] == row['outstanding_end']
        assert row['buffer_peak_mib'] <= 8
        assert 0 <= row['bandwidth_gbps'] <= 256.000001
        for port in range(4):
            assert row[f'p{port}_cumulative_accepted'] - row[f'p{port}_cumulative_completed'] == row[f'p{port}_outstanding_end']
            assert row[f'p{port}_outstanding_max'] <= cfg['outstanding']
    if mode == 'baseline':
        assert math.isclose(windows['fixed']['bandwidth_gbps'], ref['windows']['fixed']['bandwidth_gbps'], rel_tol=1e-11)
        assert dict(sim.count) == ref['counts']
    completed = [r for r in sim.req if r['end'] is not None and sim.start_us+200 <= r['end'] < sim.stop_us]
    latency = sorted(r['end'] - r['accepted'] for r in completed)
    result = dict(pattern=pattern, mode=mode, config=asdict(sim.c), windows=windows,
                  counts=dict(sim.count), actual_same_plane_bypasses=actual_bypasses,
                  issued_ca_jobs=ca_issued, runtime_seconds=time.monotonic()-start,
                  accepted_to_complete_mean_us=sum(latency)/len(latency),
                  accepted_to_complete_p99_us=latency[math.ceil(.99*len(latency))-1],
                  latency_population='Requests completed in [200,2200) us; accepted-to-last-data; completion-cohort, excludes unfinished requests',
                  model_sha256=digest('znand/model.py'), reference=str(SOURCE/reference(pattern)),
                  validation='passed: accounting, capacity, QD, in-order (simulator), FIFO no bypass; baseline throughput and counters match saved results')
    save(OUT/f'{pattern}_{mode}'/'result.json', result)
    save(OUT/f'{pattern}_{mode}'/'timeline.json', timeline)
    print(f"DONE {pattern}/{mode}: {windows['fixed']['bandwidth_gbps']:.9f} GB/s; bypasses={actual_bypasses}; {result['runtime_seconds']:.1f}s", flush=True)


def main():
    sources = sorted((SOURCE/'znand').glob('*.py'))
    inputs = [SOURCE/reference(p) for p in ('A1', 'A2', 'B')]
    inputs += [SOURCE/read(p)['config']['snapshot'] for p in inputs.copy()]
    hashes = {str(p):digest(p) for p in sources + inputs}
    save(OUT/'manifest.json', dict(source_root=str(SOURCE), hashes=hashes,
        fixed_window_us=[200,2200], only_config_change='ca_policy -> fifo',
        meaning='Disable locality and urgent-head CA reordering, retain available-plane arbitration, all other settings unchanged',
        script_sha256=digest(__file__)))
    for pattern in ('A1', 'A2', 'B'):
        for mode in ('baseline', 'fifo'):
            if not (OUT/f'{pattern}_{mode}'/'result.json').exists():
                subprocess.run([sys.executable, '-B', __file__, pattern, mode], check=True)
    assert all(digest(p)==h for p,h in hashes.items())
    rows=[]
    for pattern in ('A1','A2','B'):
        base=read(OUT/f'{pattern}_baseline'/'result.json')
        off=read(OUT/f'{pattern}_fifo'/'result.json')
        a=base['windows']['fixed']['bandwidth_gbps']; b=off['windows']['fixed']['bandwidth_gbps']
        rows.append(dict(pattern=pattern, qd_per_port=off['config']['outstanding'],
                         baseline_gbps=a, fifo_gbps=b, change_pct=(b/a-1)*100,
                         fifo_host_cap_pct=b/256*100,
                         baseline_bypasses=base['actual_same_plane_bypasses'],
                         fifo_bypasses=off['actual_same_plane_bypasses'],
                         baseline_completed_p99_us=base['accepted_to_complete_p99_us'],
                         fifo_completed_p99_us=off['accepted_to_complete_p99_us']))
    save(OUT/'comparison.json',rows)
    with (OUT/'comparison.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    save(OUT/'validation.json',dict(status='passed', paired_cases=3, unchanged_source_hashes=True,
         reproduced_saved_baselines=True, fifo_actual_bypasses_zero=True,
         scope='Conditional simulation; fixed profiles, no global optimization or hardware validation'))
    print(json.dumps(rows,indent=2),flush=True)


if __name__ == '__main__':
    if len(sys.argv)==3:
        worker(*sys.argv[1:])
    else:
        main()
