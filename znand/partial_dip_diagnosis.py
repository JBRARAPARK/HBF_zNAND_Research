"""Causal controls for the B1/B2 time-series dips; no device-model changes."""
import csv
import json
import math
import multiprocessing
import statistics
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from pathlib import Path

from .model import Config
from .partial_saturation import PartialReadSimulator, time_series
from .saturation import window_summary
from .pf_qd_sweep import digest, read
from .partial_saturation_sweep import write_csv

ROOT = Path('results/znand/partial_dips')
REFERENCE = Path('results/znand/partial_saturation')
DURATION = 1200.
WARMUP = 200.


class Observed(PartialReadSimulator):
    def __init__(self, *args, **kwargs):
        self.page_events = {}
        super().__init__(*args, **kwargs)

    def trace(self, kind, **kw):
        if kind in ('ca_start', 'sense_start', 'data_start', 'ready'):
            self.page_events.setdefault(tuple(kw['key']), []).append(dict(time_us=self.now, event=kind, **kw))
        super().trace(kind, **kw)


def run_case(pattern, control):
    base = Config(**read(REFERENCE / 'profiles' / f'{pattern}_b8_q512.json'))
    cfg = replace(base, availability=1.) if control == 'off' else replace(base, maintenance_period_us=float(control))
    sim = Observed(cfg, pattern, 65536 * 4096, duration_us=DURATION).run_for_duration()
    rows = time_series(sim)
    fixed = window_summary(rows, WARMUP, DURATION)
    selected = [r for r in rows if r['t_start_us'] >= WARMUP]
    fixed.update(bin_min_gbps=min(r['bandwidth_gbps'] for r in selected),
                 bin_max_gbps=max(r['bandwidth_gbps'] for r in selected),
                 bin_std_gbps=statistics.pstdev(r['bandwidth_gbps'] for r in selected),
                 nand_mean_gbps=statistics.mean(r['nand_completed_gbps'] for r in selected),
                 phase100_gbps=[statistics.mean(r['bandwidth_gbps'] for r in selected if int(r['t_start_us'] % 100) == phase) for phase in (0,25,50,75)])
    if control == '100':
        previous = read(REFERENCE / 'timelines' / f'{pattern}_b8_q512.json')[:len(rows)]
        for actual, expected in zip(rows, previous):
            assert actual.keys() == expected.keys()
            assert all(math.isclose(actual[k], expected[k], rel_tol=1e-10, abs_tol=1e-7) for k in actual)
    gaps = []
    byplane = {}
    for plane, left, right in sim.busy_intervals:
        byplane.setdefault(plane, []).append((left, right))
    for port in range(cfg.ports):
        req = [r for r in sim.req if r['port'] == port and r['accepted'] is not None]
        for index, r in enumerate(req):
            if 'r_start' not in r or r['head_since'] < sim.start_us + WARMUP:
                continue
            left, right = r['head_since'], r['r_start']
            if right - left < 1.:
                continue
            midpoint = (left + right) / 2
            following = [f for f in req[index+1:index+1+cfg.outstanding]
                         if f['accepted'] <= midpoint and f['ready'] is not None and f['ready'] <= midpoint]
            maintenance = [(a,b) for a,b in byplane.get(r['key'][:2], []) if a < right and b > left]
            overlap = sum(min(b,right)-max(a,left) for a,b in maintenance)
            gaps.append(dict(port=port, port_sequence=index, key=r['key'], start_us=left-sim.start_us,
                             end_us=right-sim.start_us, duration_us=right-left,
                             ready_followers_at_midpoint=len(following),
                             direct_head_plane_maintenance_overlap_us=overlap,
                             maintenance_intervals_us=[(a-sim.start_us,b-sim.start_us) for a,b in maintenance],
                             page_events=[dict(e, time_us=e['time_us']-sim.start_us) for e in sim.page_events[r['key']]]))
    overlaps = [g for g in gaps if g['direct_head_plane_maintenance_overlap_us'] > 0 and g['ready_followers_at_midpoint'] > 0]
    examples = sorted(overlaps, key=lambda g: -g['duration_us'])[:8]
    examples += [g for g in overlaps if 190 <= g['start_us'] < 225 and g not in examples][:4]
    fixed.update(gaps_at_least_1us=len(gaps), gaps_with_ready_followers=sum(g['ready_followers_at_midpoint']>0 for g in gaps),
                 gaps_with_maintenance_and_ready_followers=len(overlaps))
    return dict(pattern=pattern, control=control, config=asdict(cfg), fixed=fixed,
                baseline_prefix_matches_existing=control == '100', examples=examples,
                bins=rows, maintenance_intervals=[[list(k),a-sim.start_us,b-sim.start_us] for k,a,b in sim.busy_intervals])


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    sources = ['znand/model.py','znand/saturation.py','znand/partial_saturation.py','znand/partial_dip_diagnosis.py']
    manifest = dict(hashes={p:digest(p) for p in sources}, reference_commit='586806fa2609641f9ef77d5bec2af765b3036aaa',
                    duration_us=DURATION, warmup_us=WARMUP, controls='Only availability or maintenance_period_us changes; fixed tR, strict in-order retained')
    (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    with ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context('spawn')) as pool:
        jobs = [pool.submit(run_case,p,c) for p in ('B1','B2') for c in ('100','off','200')]
        for future in as_completed(jobs):
            result = future.result()
            name = result['pattern']+'_'+result['control']
            (ROOT/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n')
            write_csv(ROOT/(name+'.csv'), result['bins'])
            print(name, json.dumps(result['fixed']), flush=True)
    results = [read(ROOT/(p+'_'+c+'.json')) for p in ('B1','B2') for c in ('100','off','200')]
    checks = []
    for result in results:
        p, control = result['pattern'], result['control']
        base = read(REFERENCE/'profiles'/f'{p}_b8_q512.json')
        differences = [k for k in base if base[k] != result['config'][k]]
        assert differences == ([] if control == '100' else ['availability'] if control == 'off' else ['maintenance_period_us'])
        checks.append(dict(pattern=p,control=control,changed_fields=differences))
    (ROOT/'validation.json').write_text(json.dumps(dict(status='passed',cases=checks,
        original_prefix_verified=True,original_device_source_unchanged=digest('znand/model.py')=='755f822a6b7c1f44f65117b4892078419a766d4963ad4d49931e8aa1db679baf'),indent=2)+'\n')


if __name__ == '__main__':
    main()
