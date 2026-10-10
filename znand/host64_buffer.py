"""Matched 16/32MiB controller-buffer comparison for fixed-tR 64Plane reads."""
import argparse
import csv
import json
import multiprocessing
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .host64_measure import TIMINGS, audit as audit_reference, write_checked
from .pf_qd_sweep import digest, read, save
from .scheduling_sweep import SOURCE_FILES, run_case, spec
from .validate_results import validate

ROOT = Path('results/znand/planes64_buffer16')
REFERENCE = Path('results/znand/planes64')
SOURCES = (*SOURCE_FILES, 'znand/pf_qd_sweep.py', 'znand/host64_measure.py', 'znand/host64_buffer.py')


def cases():
    result = []
    for reference in read(REFERENCE / 'cases.json'):
        for mib in (32, 16):
            cfg = dict(reference['config'], buffer_pages=mib * 64)
            row = spec(reference['name'] + f'_b{mib}', 'buffer16', reference['pattern'],
                       cfg, reference['per_port'], reference['name'], f'buffer{mib}', reference['overlap'])
            row.update(case_id=len(result), layout=reference['variant'], reference_case=reference['name'])
            result.append(row)
    return result


def audit(out):
    manifest = read(out / 'manifest.json')
    assert all(digest(p) == h for p, h in manifest['hashes'].items())
    assert all(digest(REFERENCE / p) == h for p, h in manifest['reference_hashes'].items())
    assert all(digest(p) == h for p, h in manifest['snapshot_hashes'].items())
    specs = cases()
    assert specs == read(out / 'cases.json')
    rows = read(out / 'rows.json')
    historical = {r['name']: r for r in read(REFERENCE / 'rows.json')}
    assert len(rows) == len(specs) == validate(out / 'sweep.csv') == 16
    assert {r['case_id'] for r in rows} == set(range(16))
    serialized = {r['name']: r for r in csv.DictReader((out / 'sweep.csv').open())}
    by_name = {r['name']: r for r in rows}
    pairs = []
    for row in rows:
        s = specs[row['case_id']]
        assert all(row[k] == v for k, v in s.items() if k != 'config')
        assert all(row[k] == v for k, v in s['config'].items())
        assert read(out / 'profiles' / (row['name'] + '.json')) == s['config']
        assert row['planes'] == 16 and row['channels'] == 4 and row['prefetch'] is False
        assert all(row[k] == v for k, v in TIMINGS.items())
        assert row['count_sensing_reads'] == sum(row.get('count_tr_' + k, 0)
                                                for k in ('first', 'short', 'mid', 'long', 'group'))
        assert all(v == 0 for k, v in row.items() if k.startswith('count_prefetch_'))
        for k, v in row.items():
            assert serialized[row['name']][k] == (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
        if row['buffer_mib'] == 32:
            assert row['source'] == 'reused'
            previous = historical[row['reference_case']]
            for k, v in previous.items():
                if k not in ('case_id', 'name', 'stage', 'pair', 'variant', 'source'):
                    assert row[k] == v, (row['name'], k)
        else:
            assert row['source'] == 'new'
    for index in range(0, len(specs), 2):
        a, b = specs[index:index + 2]
        assert {k for k in a['config'] if a['config'][k] != b['config'][k]} == {'buffer_pages'}
        assert all(a[k] == b[k] for k in ('pattern', 'per_port', 'overlap', 'layout', 'reference_case'))
        old, new = by_name[a['name']], by_name[b['name']]
        pairs.append(dict(pair=a['pair'], buffer32_gbps=old['bandwidth_gbps'],
                          buffer16_gbps=new['bandwidth_gbps'],
                          throughput_delta_pct=(new['bandwidth_gbps'] / old['bandwidth_gbps'] - 1) * 100,
                          config_diff={'buffer_pages': [2048, 1024]}))
    result = dict(status='passed', conditions=16, new_16mib_runs=8, exact_reused_32mib_controls=8,
                  pairs=pairs, fixed_tr_us=TIMINGS, snapshots_and_workloads_unchanged=True,
                  strict_port_order_verified=True, source_hashes_and_csv_json_verified=True,
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
    audit_reference(REFERENCE)
    out = args.out
    (out / 'profiles').mkdir(parents=True, exist_ok=True)
    specs = cases()
    metadata = dict(hashes={p: digest(p) for p in SOURCES},
                    reference_hashes={p: digest(REFERENCE / p) for p in ('cases.json', 'rows.json', 'manifest.json')},
                    snapshot_hashes={s['config']['snapshot']: digest(s['config']['snapshot'])
                                     for s in specs if s['config']['snapshot']},
                    source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                    scope='Only buffer_pages changes per pair; eight new 16MiB runs and eight exact 32MiB controls.')
    checkpoint = out / 'checkpoint.json'
    if checkpoint.exists():
        previous = read(checkpoint)
        assert all(previous[k] == v for k, v in metadata.items() if k != 'source_commit')
        metadata = previous
    else:
        write_checked(checkpoint, metadata)
    write_checked(out / 'cases.json', specs)
    for s in specs:
        write_checked(out / 'profiles' / (s['name'] + '.json'), s['config'])
    rows = read(out / 'rows.json') if (out / 'rows.json').exists() else []
    done = {r['name'] for r in rows}
    historical = {r['name']: r for r in read(REFERENCE / 'rows.json')}
    for s in specs:
        if s['name'] in done or s['buffer_mib'] != 32:
            continue
        row = dict(historical[s['reference_case']])
        row.update({k: v for k, v in s.items() if k != 'config'})
        row['source'] = 'reused'
        rows.append(row)
        done.add(s['name'])
    save(out, rows)
    print(f'{len(rows)}/16 conditions available; running missing 16MiB cases', flush=True)
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(run_case, s) for s in specs if s['name'] not in done]
        for future in as_completed(futures):
            row = future.result()
            row['mean_outstanding_per_port'] = row['requests'] * row['mean_latency_us'] / row['elapsed_us'] / row['ports']
            row['source'] = 'new'
            rows.append(row)
            save(out, rows)
            print(row['name'], f"{row['bandwidth_gbps']:.6f} GB/s",
                  f"peak {row['buffer_peak_pages']/64:.3f} MiB", f'{len(rows)}/16', flush=True)
    write_checked(out / 'manifest.json', metadata)
    print(json.dumps(audit(out)), flush=True)


if __name__ == '__main__':
    main()
