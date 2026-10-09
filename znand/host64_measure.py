"""Fresh 64Plane Host-only measurements at fixed tR and two trace lengths."""
import argparse
import csv
import json
import multiprocessing
import subprocess
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .model import Config, Mapper, PAGE, workload
from .pf_qd_sweep import digest, read, save
from .scheduling_sweep import SOURCE_FILES, run_case, spec
from .validate_results import validate

ROOT = Path('results/znand/planes64')
REFERENCE = Path('results/znand/host_ceiling')
LENGTHS = (8192, 32768)
TIMINGS = dict(first_us=20.69, short_us=2., mid_us=2.08, long_us=12.16, group_us=20.69)
SOURCES = (*SOURCE_FILES, 'znand/pf_qd_sweep.py', 'znand/host64_measure.py')


def write_checked(path, value, compact=False):
    if path.exists():
        assert read(path) == value, path
    else:
        path.write_text(json.dumps(value, indent=None if compact else 2) + '\n')


def snapshot(config, pattern, length, path):
    """Static address-region mapping; no runtime knowledge of future requests."""
    c = Config(**config)
    original = Mapper(c)
    inputs = workload(pattern, c.ports, length, 0., c.host_mhz, c.seed)
    # The existing workload allocates one equally sized logical region per port.
    # Ownership here follows the address; cross-region boundary requests retain
    # the destination region even when issued by the preceding port.
    span = ((length * 4096 + PAGE * 32 - 1) // (PAGE * 32)) * PAGE * 32
    regions, owners = {}, defaultdict(set)
    for request in inputs:
        (ch, pl, q), _ = original.map(request.addr)
        packed = (q * c.planes + pl) * c.channels + ch
        region = min(c.ports - 1, request.addr // span - 1)
        assert 0 <= region < c.ports
        assert packed not in regions or regions[packed] == region
        regions[packed] = region
        owners[packed].add(request.port)
    ranks = defaultdict(int)
    mapping = {}
    per_region = c.planes // c.ports
    for packed, region in sorted(regions.items()):
        ch = packed % c.channels
        rank = ranks[region, ch]
        ranks[region, ch] += 1
        mapping[str(packed)] = [ch, region * per_region + rank % per_region, rank // per_region]
    doc = dict(page_bytes=PAGE, model_geometry=dict(channels=4, planes_per_channel=16),
               mapping=mapping, logical_region_span_bytes=span,
               provenance='Synthetic static address-region layout; no dynamic L2P or MQSim data.')
    write_checked(path, doc, compact=True)
    changed = Mapper(Config(**dict(config, snapshot=str(path))))
    assert len(set(map(tuple, mapping.values()))) == len(mapping)
    cross = 0
    for request in inputs:
        before, offset = original.map(request.addr)
        after, new_offset = changed.map(request.addr)
        assert before[0] == after[0] and offset == new_offset
        cross += after[1] // per_region != request.port
    if length == 8192:
        previous = read(REFERENCE / 'snapshots' / f'{pattern}_64Plane.json')
        assert mapping == previous['mapping']
    return dict(pattern=pattern, per_port=length, mapped_pages=len(mapping),
                channel_and_offset_preserved=True, injective=True,
                shared_boundary_pages=sum(len(v) > 1 for v in owners.values()),
                cross_region_requests=cross, snapshot_sha256=digest(path))


def build(out):
    (out / 'snapshots').mkdir(parents=True, exist_ok=True)
    (out / 'profiles').mkdir(exist_ok=True)
    cases, checks = [], {}
    previous = read(REFERENCE / 'cases.json')
    for length in LENGTHS:
        for pattern in ('A1', 'A2'):
            baseline = next(s['config'] for s in previous
                            if s['name'] == f'{pattern}_64Plane_baseline')
            path = out / 'snapshots' / f'{pattern}_n{length}.json'
            checks[str(path)] = snapshot(baseline, pattern, length, path)
            for variant in ('baseline', 'region_layout'):
                config = dict(baseline, snapshot=str(path) if variant == 'region_layout' else '')
                assert config['planes'] == 16 and config['channels'] == 4
                assert all(config[k] == v for k, v in TIMINGS.items())
                name = f'{pattern}_64Plane_n{length}_{variant}'
                case = spec(name, 'fresh_64plane', pattern, config, length,
                            pair=f'{pattern}_n{length}', variant=variant)
                case['case_id'] = len(cases)
                cases.append(case)
                write_checked(out / 'profiles' / f'{name}.json', config)
    return cases, checks


def audit(out):
    manifest = read(out / 'manifest.json')
    assert all(digest(p) == h for p, h in manifest['hashes'].items())
    assert digest(REFERENCE / 'rows.json') == manifest['reference_rows_sha256']
    assert digest(REFERENCE / 'cases.json') == manifest['reference_cases_sha256']
    cases, checks = build(out)
    assert cases == read(out / 'cases.json')
    assert checks == read(out / 'snapshot_validation.json')
    rows = read(out / 'rows.json')
    assert len(rows) == len(cases) == validate(out / 'sweep.csv') == 8
    assert {r['case_id'] for r in rows} == set(range(8))
    serialized = {r['name']: r for r in csv.DictReader((out / 'sweep.csv').open())}
    historical = {r['name']: r for r in read(REFERENCE / 'rows.json')}
    reproduced = []
    for row in rows:
        case = cases[row['case_id']]
        assert all(row[k] == v for k, v in case.items() if k != 'config')
        assert all(row[k] == v for k, v in case['config'].items())
        assert row['prefetch'] is False and row['source'] == 'fresh'
        assert row['count_sensing_reads'] == sum(row.get('count_tr_' + k, 0)
                                                for k in ('first', 'short', 'mid', 'long', 'group'))
        assert all(v == 0 for k, v in row.items() if k.startswith('count_prefetch_'))
        assert row['inclusive_prefetch_gbps'] == row['bandwidth_gbps']
        for k, v in row.items():
            assert serialized[row['name']][k] == (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
        if row['per_port'] == 8192:
            old = historical[f"{row['pattern']}_64Plane_{row['variant']}"]
            exclude = {'name', 'stage', 'pair', 'case_id', 'snapshot', 'source', 'source_case', 'runtime_seconds'}
            for k, v in old.items():
                if k not in exclude:
                    assert row[k] == v, (row['name'], k, row.get(k), v)
            reproduced.append(row['name'])
    for pair in {s['pair'] for s in cases}:
        a, b = [s['config'] for s in cases if s['pair'] == pair]
        assert {k for k in a if a[k] != b[k]} == {'snapshot'}
    result = dict(status='passed', fresh_runs=8, reused_results=0,
                  reproduced_8192_cases=reproduced, identical_timing_all_cases=TIMINGS,
                  geometry='4 channels x 16 Planes = 64 independent Planes',
                  snapshot_only_difference_in_four_pairs=True,
                  strict_port_order_checked_in_every_run=True,
                  csv_json_and_source_hashes_verified=True,
                  sweep_sha256=digest(out / 'sweep.csv'))
    (out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if args.validate_only:
        print(json.dumps(audit(args.out)))
        return
    assert args.workers > 0
    out = args.out
    cases, checks = build(out)
    metadata = dict(hashes={p: digest(p) for p in SOURCES},
                    reference_rows_sha256=digest(REFERENCE / 'rows.json'),
                    reference_cases_sha256=digest(REFERENCE / 'cases.json'),
                    source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                    scope='Eight fresh runs, 64Plane, fixed tR, no reused measurement rows.')
    checkpoint = out / 'checkpoint.json'
    if checkpoint.exists():
        old = read(checkpoint)
        assert all(old[k] == v for k, v in metadata.items() if k != 'source_commit')
        metadata = old
    else:
        write_checked(checkpoint, metadata)
    write_checked(out / 'cases.json', cases)
    write_checked(out / 'snapshot_validation.json', checks)
    rows = read(out / 'rows.json') if (out / 'rows.json').exists() else []
    done = {r['name'] for r in rows}
    print(f'64Plane fixed-tR experiment: {len(done)}/8 completed', flush=True)
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(run_case, s) for s in cases if s['name'] not in done]
        for future in as_completed(futures):
            row = future.result()
            row['mean_outstanding_per_port'] = row['requests'] * row['mean_latency_us'] / row['elapsed_us'] / row['ports']
            row['source'] = 'fresh'
            rows.append(row)
            save(out, rows)
            print(row['name'], f"{row['bandwidth_gbps']:.6f} GB/s",
                  f"middle {row['middle_bandwidth_gbps']:.6f}", f'{len(rows)}/8', flush=True)
    write_checked(out / 'manifest.json', metadata)
    print(json.dumps(audit(out)), flush=True)


if __name__ == '__main__':
    main()
