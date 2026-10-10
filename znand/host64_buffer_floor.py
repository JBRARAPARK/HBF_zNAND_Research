"""Measure the controller-buffer floor for 200GB/s with the fixed 64Plane layout.

Append independently measured capacities using --mib. Preserve the reference
workloads, snapshots, timing and scheduling; change only buffer_pages.
"""
import argparse
import csv
import json
import math
import multiprocessing
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .host64_buffer import ROOT as REFERENCE, audit as audit_reference
from .host64_measure import TIMINGS, write_checked
from .pf_qd_sweep import digest, read, save
from .scheduling_sweep import SOURCE_FILES, run_case, spec
from .validate_results import validate

ROOT = Path('results/znand/planes64_buffer_floor')
SOURCES = (*SOURCE_FILES, 'znand/pf_qd_sweep.py', 'znand/host64_measure.py',
           'znand/host64_buffer.py', 'znand/host64_buffer_floor.py')
TARGET = 200.


def references():
    return {r['name']: r for r in read(REFERENCE / 'rows.json')
            if r['layout'] == 'region_layout'}


def make_case(pattern, length, pages, case_id):
    name = f'{pattern}_64Plane_n{length}_region_layout_bp{pages}'
    base_name = f'{pattern}_64Plane_n{length}_region_layout_b32'
    original = next(s for s in read(REFERENCE / 'cases.json') if s['name'] == base_name)
    cfg = dict(original['config'], buffer_pages=pages)
    result = spec(name, 'buffer_floor', pattern, cfg, length,
                  f'{pattern}_n{length}', f'buffer_pages_{pages}', original['overlap'])
    result.update(case_id=case_id, layout='region_layout', reference_case=base_name)
    return result


def audit(out):
    metadata = read(out / 'manifest.json')
    for section in ('hashes', 'reference_hashes', 'snapshot_hashes'):
        assert all(digest(p) == h for p, h in metadata[section].items()), section
    specs = read(out / 'cases.json')
    rows = read(out / 'rows.json')
    assert len(rows) == len(specs) == validate(out / 'sweep.csv')
    assert {r['case_id'] for r in rows} == set(range(len(specs)))
    assert len({r['name'] for r in rows}) == len(rows)
    serialized = {r['name']: r for r in csv.DictReader((out / 'sweep.csv').open())}
    previous = references()
    for row in rows:
        s = specs[row['case_id']]
        assert s == make_case(s['pattern'], s['per_port'], s['config']['buffer_pages'], s['case_id'])
        assert all(row[k] == v for k, v in s.items() if k != 'config')
        assert all(row[k] == v for k, v in s['config'].items())
        assert read(out / 'profiles' / (row['name'] + '.json')) == s['config']
        assert row['ports'] == 4 and row['channels'] == 4 and row['planes'] == 16
        assert row['prefetch'] is False and row['outstanding'] == 2048
        assert all(row[k] == v for k, v in TIMINGS.items())
        assert row['count_sensing_reads'] == sum(row.get('count_tr_' + k, 0)
                                                for k in ('first', 'short', 'mid', 'long', 'group'))
        assert all(v == 0 for k, v in row.items() if k.startswith('count_prefetch_'))
        assert row['inclusive_prefetch_gbps'] == row['bandwidth_gbps']
        assert math.isclose(row['mean_outstanding_per_port'],
                            row['per_port'] * row['mean_latency_us'] / row['elapsed_us'])
        states = [v for k, v in row.items()
                  if k.startswith('diag_buffer_mean_') and k != 'diag_buffer_mean_total_mib']
        assert math.isclose(sum(states), row['diag_buffer_mean_total_mib'], abs_tol=1e-9)
        original = previous[row['reference_case']]
        assert all(row[k] == original[k] for k in s['config'] if k != 'buffer_pages')
        if row['source'] == 'reused':
            source = previous[row['source_case']]
            excluded = {'name', 'stage', 'pair', 'variant', 'case_id', 'reference_case', 'source', 'source_case'}
            assert all(row[k] == v for k, v in source.items() if k not in excluded)
        else:
            assert row['source'] == 'new'
        for k, v in row.items():
            assert serialized[row['name']][k] == (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
    minima = []
    for length in sorted({r['per_port'] for r in rows}):
        for pattern in ('A1', 'A2'):
            group = sorted((r for r in rows if (r['pattern'], r['per_port']) == (pattern, length)),
                           key=lambda r: r['buffer_pages'])
            if not group:
                continue
            passes = [r for r in group if r['bandwidth_gbps'] >= TARGET]
            best = passes[0] if passes else None
            lower = [r for r in group if best and r['buffer_pages'] < best['buffer_pages']]
            minima.append(dict(pattern=pattern, per_port=length,
                minimum_tested_passing_mib=best['buffer_mib'] if best else None,
                passing_gbps=best['bandwidth_gbps'] if best else None,
                nearest_lower_tested_mib=lower[-1]['buffer_mib'] if lower else None,
                nearest_lower_gbps=lower[-1]['bandwidth_gbps'] if lower else None,
                tested_mib=[r['buffer_mib'] for r in group],
                nonmonotonic_steps=[dict(from_mib=a['buffer_mib'], to_mib=b['buffer_mib'])
                                    for a, b in zip(group, group[1:])
                                    if b['bandwidth_gbps'] < a['bandwidth_gbps'] - 1e-8]))
    result = dict(status='passed', measured_conditions=len(rows), target_gbps=TARGET,
                  target_metric='Whole cold-run useful Host bytes / first-offer-to-last-return time',
                  new_runs=sum(r['source'] == 'new' for r in rows),
                  exact_reused_controls=sum(r['source'] == 'reused' for r in rows),
                  fixed_tr_us=TIMINGS, config_difference_only_buffer_pages=True,
                  source_snapshot_and_reference_hashes_verified=True,
                  strict_port_order_and_accounting_verified=True,
                  minima=minima, sweep_sha256=digest(out / 'sweep.csv'))
    (out / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--mib', type=float, nargs='+', default=[32, 16, 8, 4, 2, 1, 6, 10, 12])
    parser.add_argument('--lengths', type=int, nargs='+', choices=(8192, 32768), default=[32768, 8192])
    parser.add_argument('--patterns', nargs='+', choices=('A1', 'A2'), default=['A1', 'A2'])
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if args.validate_only:
        print(json.dumps(audit(args.out)))
        return
    assert args.workers > 0
    pages = []
    for mib in args.mib:
        assert math.isfinite(mib) and mib * 64 == int(mib * 64) and mib * 64 >= 5
        pages.append(int(mib * 64))
    audit_reference(REFERENCE)
    out = args.out
    (out / 'profiles').mkdir(parents=True, exist_ok=True)
    historical = references()
    snapshots = {r['snapshot'] for r in historical.values()}
    metadata = dict(hashes={p: digest(p) for p in SOURCES},
                    reference_hashes={str(REFERENCE / p): digest(REFERENCE / p)
                                      for p in ('cases.json', 'rows.json', 'manifest.json')},
                    snapshot_hashes={p: digest(p) for p in snapshots},
                    source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                    scope='Fixed layout, timing, scheduler, QD and workload; buffer_pages only. '
                          'Capacities may be appended to refine observed 200GB/s crossings.')
    checkpoint = out / 'checkpoint.json'
    if checkpoint.exists():
        old = read(checkpoint)
        assert all(old[k] == v for k, v in metadata.items() if k != 'source_commit')
        metadata = old
    else:
        write_checked(checkpoint, metadata)
    specs = read(out / 'cases.json') if (out / 'cases.json').exists() else []
    names = {s['name'] for s in specs}
    for length in args.lengths:
        for page_count in pages:
            for pattern in args.patterns:
                s = make_case(pattern, length, page_count, len(specs))
                if s['name'] not in names:
                    specs.append(s)
                    names.add(s['name'])
    (out / 'cases.json').write_text(json.dumps(specs, indent=2) + '\n')
    for s in specs:
        write_checked(out / 'profiles' / (s['name'] + '.json'), s['config'])
    rows = read(out / 'rows.json') if (out / 'rows.json').exists() else []
    done = {r['name'] for r in rows}
    for s in specs:
        if s['name'] in done or s['buffer_mib'] not in (16, 32):
            continue
        source_name = s['reference_case'].rsplit('_b', 1)[0] + f"_b{int(s['buffer_mib'])}"
        row = dict(historical[source_name])
        row.update({k: v for k, v in s.items() if k != 'config'})
        row.update(source='reused', source_case=source_name)
        rows.append(row)
        done.add(s['name'])
    save(out, rows)
    print(f'{len(rows)}/{len(specs)} conditions available', flush=True)
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(run_case, s) for s in specs if s['name'] not in done]
        for future in as_completed(futures):
            row = future.result()
            row['mean_outstanding_per_port'] = row['per_port'] * row['mean_latency_us'] / row['elapsed_us']
            row.update(source='new', source_case='')
            rows.append(row)
            save(out, rows)
            print(row['name'], f"{row['bandwidth_gbps']:.6f} GB/s",
                  f"Long {row.get('count_tr_long', 0)}", f'{len(rows)}/{len(specs)}', flush=True)
    write_checked(out / 'manifest.json', metadata)
    result = audit(out)
    print(json.dumps({k: v for k, v in result.items() if k != 'minima'}), flush=True)
    for row in result['minima']:
        print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
