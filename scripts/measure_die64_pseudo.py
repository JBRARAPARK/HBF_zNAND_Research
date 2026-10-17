"""4 DIE x 2 independent pseudo channels x 8 planes: topology and placement study.

The same CA/Data resources and timings are used as the previous flat 8x8 model.
Concentration changes static page placement, not installed NAND geometry.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from znand.model import Config, Mapper, PAGE
from znand.saturation import time_series, summarize
from znand.read64_observation import NoPrefetchCapacitySimulator, time_series as series64
from znand.partial_saturation import summarize_partial
from measure_restored64 import ObservedA

OUT = ROOT / 'results/local/die64_pseudo_20261017'
LAYOUTS = {'all8': list(range(8)), 'one_pc': [0], 'same_die2': [0, 1],
           'split_die2': [0, 2], 'one_pc_per_die4': [0, 2, 4, 6]}
SOURCE_FILES = ['znand/model.py', 'znand/saturation.py', 'znand/read64_observation.py',
                'znand/partial_saturation.py', 'znand/workloads.py',
                'scripts/measure_restored64.py', 'scripts/measure_die64_pseudo.py']

def read(path): return json.loads(Path(path).read_text())
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')

def prepare(out):
    assert not (out / 'manifest.json').exists(), 'Use a fresh output directory'
    checks = []
    for stripe in (4096, 16384):
        source = ROOT / f'results/znand/channel_split64/snapshots/s{stripe}.json'
        original = read(source)
        for layout, channels in LAYOUTS.items():
            n = len(channels)
            mapping = {key: [channels[ch % n], pl, q * (8 // n) + ch // n]
                       for key, (ch, pl, q) in original['mapping'].items()}
            assert len(set(map(tuple, mapping.values()))) == len(mapping)
            assert {ch for ch, pl, q in mapping.values()} == set(channels)
            assert {pl for ch, pl, q in mapping.values()} == set(range(8))
            assert all(mapping[key][1] == value[1] for key, value in original['mapping'].items())
            if layout == 'all8': assert mapping == original['mapping']
            path = out / 'snapshots' / f'{layout}_s{stripe}.json'
            doc = dict(original, model_geometry=Config.die64().model_geometry, mapping=mapping,
                       provenance='Explicit DIE hierarchy; static channel concentration retaining packed 16KiB pages and region Plane groups',
                       source_snapshot_sha256=digest(source), active_pseudo_channels=channels)
            save(path, doc)
            c = Config.die64(stripe=stripe, snapshot=str(path))
            mapper = Mapper(c)
            # The mapper validates every key. Check the full input domain and all offsets.
            offsets = {}; groups = [set() for _ in range(4)]
            span = doc['logical_region_span_bytes']
            for region in range(4):
                for logical in range(span // 4096):
                    key, off = mapper.map((region + 1) * span + logical * 4096)
                    assert key[1] // 2 == region
                    offsets.setdefault(key, set()).add(off)
                    groups[region].add(key[:2])
            assert all(v == {0, 4096, 8192, 12288} for v in offsets.values())
            assert all(len(g) == 2 * n for g in groups)
            checks.append(dict(layout=layout, stripe=stripe, mapped_pages=len(mapping),
                               active_planes=8 * n, planes_per_region=2 * n,
                               bijective=True, complete_page_offsets=True,
                               region_groups_disjoint=True, sha256=digest(path)))
            Mapper.map.cache_clear()
    cases = []
    for layout in LAYOUTS:
        for pattern in ('A1', 'A2'):
            cases.append(dict(name=f'half_bw_{layout}_{pattern}', variant='half_bw', layout=layout, pattern=pattern))
    for variant, pattern in [('full_bw', 'A1'), ('full_bw', 'A2'), ('half_bw', 'B'), ('full_bw', 'B')]:
        cases.append(dict(name=f'{variant}_all8_{pattern}', variant=variant, layout='all8', pattern=pattern))
    for case in cases:
        cfg = read(ROOT / f"configs/channel_split64/{case['variant']}/{case['pattern']}.json")
        cfg.update(dies=4, channels_per_die=2,
                   snapshot=str((out / 'snapshots' / f"{case['layout']}_s{cfg['stripe']}.json").relative_to(ROOT)))
        Config(**cfg).validate()
        save(out / 'profiles' / f"{case['name']}.json", cfg)
    save(out / 'snapshot_validation.json', checks)
    save(out / 'cases.json', cases)
    save(out / 'manifest.json', dict(base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
         source_hashes={p: digest(ROOT / p) for p in SOURCE_FILES},
         input_hashes={str(p.relative_to(ROOT)): digest(p) for sub in ('profiles', 'snapshots') for p in (out / sub).glob('*.json')},
         duration_us=2200, warmup_us=200, bin_us=25, seed=7,
         assumption='Two independent CA/Data paths per DIE; no additional DIE shared busy/power limit',
         concentration='Installed 64Plane geometry unchanged; active PC and Plane counts change with placement'))
    return cases

def run_case(args):
    out, case = args
    start = time.monotonic()
    c = Config(**read(out / 'profiles' / f"{case['name']}.json"))
    span = read(ROOT / c.snapshot)['logical_region_span_bytes']
    a = case['pattern'] != 'B'
    sim = (ObservedA if a else NoPrefetchCapacitySimulator)(c, case['pattern'], span, 2200.)
    sim.run_for_duration()
    rows = (time_series if a else series64)(sim, 25.)
    windows = (summarize if a else summarize_partial)(rows, 200., 500.)
    counts = Counter(ch for t, (ch, pl, q) in sim.nand_transfers if sim.start_us + 200 <= t < sim.stop_us)
    result = dict(case, config=asdict(c), nand_topology=c.topology(), windows=windows,
                  fixed_pc_nand_gbps=[counts[ch] * PAGE / 2000 / 1000 for ch in range(8)],
                  fixed_sensing_counts=dict(Counter(kind for t, kind in sim.sensing if sim.start_us + 200 <= t < sim.stop_us)),
                  counts=dict(sim.count), per_port_generated=sim.sequence, peak_buffer_mib=sim.used_peak / 64,
                  runtime_seconds=time.monotonic() - start)
    result['fixed_die_nand_gbps'] = [sum(result['fixed_pc_nand_gbps'][i:i+2]) for i in range(0, 8, 2)]
    save(out / case['name'] / 'timeline.json', rows)
    save(out / case['name'] / 'result.json', result)
    print('DONE', case['name'], round(windows['fixed']['bandwidth_gbps'], 6), 'GB/s',
          round(result['runtime_seconds'], 1), 'seconds', flush=True)
    return case['name']

def audit(out):
    manifest = read(out / 'manifest.json')
    for path, sha in manifest['source_hashes'].items(): assert digest(ROOT / path) == sha
    for path, sha in manifest['input_hashes'].items(): assert digest(ROOT / path) == sha
    summary = []
    for case in read(out / 'cases.json'):
        r = read(out / case['name'] / 'result.json'); rows = read(out / case['name'] / 'timeline.json')
        c = Config(**r['config']); c.validate()
        assert r['config'] == read(out / 'profiles' / f"{case['name']}.json")
        assert r['nand_topology'] == c.topology() and r['peak_buffer_mib'] <= 8
        span = read(ROOT / c.snapshot)['logical_region_span_bytes']
        assert max(r['per_port_generated']) * (64 if case['pattern'] == 'B' else 4096) <= span
        assert len(rows) == 88
        assert r['windows'] == (summarize_partial if case['pattern'] == 'B' else summarize)(rows, 200., 500.)
        for i, row in enumerate(rows):
            assert (row['t_start_us'], row['t_end_us']) == (i * 25, (i + 1) * 25)
            assert row['cumulative_accepted'] - row['cumulative_completed'] == row['outstanding_end']
            assert row['buffer_peak_mib'] <= 8 and 0 <= row['bandwidth_gbps'] <= 256.000001
            for p in range(4):
                assert row[f'p{p}_cumulative_accepted'] - row[f'p{p}_cumulative_completed'] == row[f'p{p}_outstanding_end']
                assert row[f'p{p}_outstanding_max'] <= c.outstanding
        f = r['windows']['fixed']; channels = LAYOUTS[case['layout']]
        assert all(v == 0 for ch, v in enumerate(r['fixed_pc_nand_gbps']) if ch not in channels)
        identical = None
        if case['layout'] == 'all8':
            old_root = ROOT / f"results/znand/channel_split64/{case['variant']}/{case['pattern']}"
            old = read(old_root / 'result.json')
            assert rows == read(old_root / 'timeline.json')
            assert r['windows'] == old['windows'] and r['counts'] == old['counts']
            assert r['fixed_sensing_counts'] == old['fixed_sensing_counts']
            identical = True
        summary.append(dict(case, active_pcs=len(channels), active_planes=8 * len(channels),
                            host_gbps=f['bandwidth_gbps'], per_port_gbps=f['p_bandwidth_gbps'],
                            actual_outstanding=f['p_outstanding_mean'],
                            nand_pc_gbps=r['fixed_pc_nand_gbps'], nand_die_gbps=r['fixed_die_nand_gbps'],
                            second_vs_first_pct=r['windows']['second_vs_first_pct'],
                            flat_reference_timeline_identical=identical))
    save(out / 'summary.json', summary)
    with (out / 'summary.csv').open('w') as file:
        w = csv.DictWriter(file, list(summary[0])); w.writeheader(); w.writerows(summary)
    save(out / 'validation.json', dict(status='passed', cases=len(summary),
         all_six_flat_references_identical=True, hashes_accounting_qd_capacity_verified=True,
         inactive_pcs_have_zero_transfers=True, fixed_window_us=[200, 2200]))
    print('VALIDATED', len(summary), 'cases; six exact flat-reference comparisons', flush=True)

def main():
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path, default=OUT)
    p.add_argument('--workers', type=int, default=2); p.add_argument('--validate', action='store_true')
    p.add_argument('--resume', action='store_true'); args = p.parse_args(); out = args.out.resolve()
    if args.validate: audit(out); return
    if args.resume:
        m = read(out / 'manifest.json')
        assert all(digest(ROOT / path) == sha for path, sha in m['source_hashes'].items())
        cases = read(out / 'cases.json')
    else: cases = prepare(out)
    pending = [c for c in cases if not (out / c['name'] / 'result.json').exists()]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run_case, [(out, c) for c in pending if c['pattern'] != 'B']))
    for case in pending:
        if case['pattern'] == 'B': run_case((out, case))
    audit(out)

if __name__ == '__main__': main()
