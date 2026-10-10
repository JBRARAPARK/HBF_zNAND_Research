"""Continuous-load, fixed-time buffer x device-QD experiment with time series."""
import argparse
import csv
import json
import math
import multiprocessing
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from .host64_measure import snapshot, write_checked, TIMINGS
from .model import Config
from .pf_qd_sweep import digest, read
from .saturation import SaturatedSimulator, time_series, summarize

ROOT = Path('results/znand/saturation')
REFERENCE = Path('results/znand/planes64/profiles')
SOURCES = ('znand/model.py', 'znand/saturation.py', 'znand/saturation_sweep.py',
           'znand/host64_measure.py', 'znand/pf_qd_sweep.py', 'test_znand_saturation.py')
DOMAIN_REQUESTS = 65536
DURATION_US = 2200.
WARMUP_US = 200.
BIN_US = 25.
PEAK_US = 500.


def write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0])
    with path.open('w', newline='') as file:
        writer = csv.DictWriter(file, keys, lineterminator='\n')
        writer.writeheader()
        writer.writerows({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()} for row in rows)


def run_case(case):
    started = time.monotonic()
    config = Config(**case['config'])
    span = DOMAIN_REQUESTS * 4096
    sim = SaturatedSimulator(config, case['pattern'], span, DURATION_US).run_for_duration()
    timeline = time_series(sim, BIN_US)
    windows = summarize(timeline, WARMUP_US, PEAK_US)
    result = dict(name=case['name'], pattern=case['pattern'], buffer_mib=case['buffer_mib'],
                  configured_qd_per_port=config.outstanding, windows=windows,
                  cumulative_accepted=timeline[-1]['cumulative_accepted'],
                  cumulative_completed=timeline[-1]['cumulative_completed'],
                  outstanding_at_stop=timeline[-1]['outstanding_end'],
                  host_pending_at_stop=[len(q) for q in sim.sources],
                  per_port_generated=sim.sequence, counts=dict(sim.count),
                  peak_buffer_mib=sim.used_peak / 64, config=asdict(config),
                  duration_us=DURATION_US, warmup_us=WARMUP_US, bin_us=BIN_US,
                  peak_window_us=PEAK_US, runtime_seconds=time.monotonic() - started)
    return result, timeline


def flat_row(result):
    fixed, peak = result['windows']['fixed'], result['windows']['peak']
    return dict(name=result['name'], pattern=result['pattern'], buffer_mib=result['buffer_mib'],
                configured_qd_per_port=result['configured_qd_per_port'],
                fixed_gbps=fixed['bandwidth_gbps'], peak_500us_gbps=peak['bandwidth_gbps'],
                peak_start_us=peak['start_us'], peak_end_us=peak['end_us'],
                fixed_actual_outstanding=fixed['outstanding_mean'],
                fixed_actual_outstanding_per_port=fixed['p_outstanding_mean'],
                fixed_per_port_gbps=fixed['p_bandwidth_gbps'],
                fixed_accepted_requests=fixed['accepted_requests'],
                fixed_completed_requests=fixed['completed_requests'],
                peak_actual_outstanding=peak['outstanding_mean'],
                peak_completed_requests=peak['completed_requests'],
                peak_buffer_mib=result['peak_buffer_mib'],
                second_vs_first_pct=result['windows']['second_vs_first_pct'])


def audit(out):
    meta = read(out / 'manifest.json')
    assert all(digest(p) == h for p, h in meta['hashes'].items())
    assert all(digest(p) == h for p, h in meta['snapshots'].items())
    specs = read(out / 'cases.json')
    rows = []
    for case in specs:
        result = read(out / 'runs' / (case['name'] + '.json'))
        timeline = read(out / 'timelines' / (case['name'] + '.json'))
        assert result['config'] == case['config']
        assert all(result['config'][k] == v for k, v in TIMINGS.items())
        assert result['windows'] == summarize(timeline, WARMUP_US, PEAK_US)
        assert len(timeline) == int(DURATION_US / BIN_US)
        assert result['cumulative_accepted'] - result['cumulative_completed'] == result['outstanding_at_stop']
        assert result['host_pending_at_stop'] == [1] * 4
        assert max(result['per_port_generated']) < DOMAIN_REQUESTS
        assert result['peak_buffer_mib'] <= case['buffer_mib']
        assert not result['config']['prefetch']
        for index, row in enumerate(timeline):
            assert row['t_start_us'] == index * BIN_US
            assert row['cumulative_accepted'] - row['cumulative_completed'] == row['outstanding_end']
            assert 0 <= row['bandwidth_gbps'] <= 256 + 1e-6
            for port in range(4):
                assert row[f'p{port}_cumulative_accepted'] - row[f'p{port}_cumulative_completed'] == row[f'p{port}_outstanding_end']
                assert 0 <= row[f'p{port}_outstanding_min'] <= row[f'p{port}_outstanding_mean'] + 1e-7
                assert row[f'p{port}_outstanding_mean'] <= row[f'p{port}_outstanding_max'] + 1e-7
                assert row[f'p{port}_outstanding_max'] <= case['config']['outstanding']
            if index:
                prev = timeline[index - 1]
                assert row['cumulative_accepted'] - prev['cumulative_accepted'] == row['accepted_requests']
                assert row['cumulative_completed'] - prev['cumulative_completed'] == row['completed_requests']
        with (out / 'timelines' / (case['name'] + '.csv')).open() as file:
            serialized = list(csv.DictReader(file))
        assert len(serialized) == len(timeline)
        assert all(str(v) == serialized[i][k] for i, row in enumerate(timeline) for k, v in row.items())
        rows.append(flat_row(result))
    assert rows == read(out / 'rows.json')
    checked = dict(status='passed', conditions=len(specs), source_hashes_verified=True,
                   timelines_and_windows_verified=True, unfinished_work_excluded_from_duration_denominator=True,
                   all_ports_continuously_supplied=True, port_order_checked_during_runs=True,
                   actual_outstanding_accounting_verified=True, fixed_tr_us=TIMINGS,
                   definition='Device outstanding = accepted request minus final response completed',
                   fixed_window_us=[WARMUP_US, DURATION_US], best_window_us=PEAK_US,
                   sweep_sha256=digest(out / 'sweep.csv'))
    (out / 'validation.json').write_text(json.dumps(checked, indent=2) + '\n')
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--buffers', type=float, nargs='+', default=[4, 8, 16])
    parser.add_argument('--qds', type=int, nargs='+', default=[128, 256, 512, 1024, 2048])
    parser.add_argument('--patterns', nargs='+', choices=('A1', 'A2'), default=['A1', 'A2'])
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if args.validate_only:
        print(json.dumps(audit(args.out)))
        return
    out = args.out
    for folder in ('profiles', 'snapshots', 'runs', 'timelines'):
        (out / folder).mkdir(parents=True, exist_ok=True)
    base = {}
    for pattern in ('A1', 'A2'):
        cfg = read(REFERENCE / f'{pattern}_64Plane_n32768_region_layout.json')
        path = out / 'snapshots' / (pattern + '.json')
        if not path.exists():
            snapshot(dict(cfg, snapshot=''), pattern, DOMAIN_REQUESTS, path)
        base[pattern] = dict(cfg, snapshot=str(path))
    meta = dict(hashes={p: digest(p) for p in SOURCES},
                snapshots={cfg['snapshot']: digest(cfg['snapshot']) for cfg in base.values()},
                source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                domain_requests_per_port=DOMAIN_REQUESTS,
                duration_us=DURATION_US, warmup_us=WARMUP_US, bin_us=BIN_US, peak_window_us=PEAK_US,
                source='Continuous next request per port; refill on AR acceptance, limited by existing device QD/admission',
                throughput='Host payload transfer bytes intersecting each time bin; completed-command counts also recorded')
    checkpoint = out / 'manifest.json'
    if checkpoint.exists():
        old = read(checkpoint)
        assert all(old[k] == v for k, v in meta.items() if k != 'source_commit')
    else:
        write_checked(checkpoint, meta)
    cases = read(out / 'cases.json') if (out / 'cases.json').exists() else []
    names = {case['name'] for case in cases}
    for mib in args.buffers:
        assert mib * 64 == int(mib * 64)
        for qd in args.qds:
            for pattern in args.patterns:
                name = f'{pattern}_b{mib:g}_q{qd}'
                if name in names:
                    continue
                cfg = dict(base[pattern], buffer_pages=int(mib * 64), outstanding=qd)
                cases.append(dict(name=name, pattern=pattern, buffer_mib=mib, config=cfg))
                names.add(name)
                write_checked(out / 'profiles' / (name + '.json'), cfg)
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    todo = [case for case in cases if not (out / 'runs' / (case['name'] + '.json')).exists()]
    print(f'{len(cases)-len(todo)}/{len(cases)} complete; continuous-load time benchmark', flush=True)
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(run_case, case) for case in todo]
        for future in as_completed(futures):
            result, timeline = future.result()
            name = result['name']
            write_checked(out / 'timelines' / (name + '.json'), timeline)
            write_csv(out / 'timelines' / (name + '.csv'), timeline)
            write_checked(out / 'runs' / (name + '.json'), result)
            row = flat_row(result)
            print(name, f"mean {row['fixed_gbps']:.3f} GB/s, peak500 {row['peak_500us_gbps']:.3f}, "
                  f"actual QD {row['fixed_actual_outstanding_per_port']}, {result['runtime_seconds']:.1f}s", flush=True)
    rows = [flat_row(read(out / 'runs' / (case['name'] + '.json'))) for case in cases]
    (out / 'rows.json').write_text(json.dumps(rows, indent=2) + '\n')
    write_csv(out / 'sweep.csv', rows)
    print(json.dumps(audit(out)), flush=True)


if __name__ == '__main__':
    main()
