"""Reproducible B workload measurements; existing NAND/controller model unchanged."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

from .partial_saturation import summarize_partial

ROOT = Path('results/znand/b_sequential')
BASE = Path('results/znand/saturation/profiles/A1_b8_q512.json')
SOURCES = ('znand/model.py', 'znand/workloads.py', 'znand/saturation.py',
           'znand/partial_saturation.py', 'znand/stream64.py', 'znand/read64_observation.py')


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def audit(out):
    manifest = read(out / 'manifest.json')
    assert all(digest(p) == h for p, h in manifest['hashes'].items())
    if 'legacy_observer_manifest' in manifest:
        old=read(out/manifest['legacy_observer_manifest'])
        for source,expected in old['hashes'].items():
            if digest(source)!=expected:
                payload=subprocess.check_output(['git','show',old['source_commit']+':'+source])
                assert hashlib.sha256(payload).hexdigest()==expected
    base = read(BASE)
    rows = []
    for path in sorted((out / 'cases').glob('*/result.json')):
        result = read(path)
        timeline = read(path.with_name('timeline.json'))
        cfg = result['config']
        assert result['pattern'] == 'B' and result['workload_schema'] == 2
        if result.get('observation_version',1)==1:
            assert path.parent.name in manifest.get('legacy_observer_cases',[])
        else:
            assert result['observation_version']==2
        assert result['model_sha256'] == digest('znand/model.py')
        assert cfg == base | {k: cfg[k] for k in ('buffer_pages', 'outstanding')}
        assert result['windows'] == summarize_partial(timeline, 200., 500.)
        assert len(timeline) == 88 and result['duration_us'] == 2200.
        assert result['warmup_us'] == 200. and result['bin_us'] == 25.
        assert max(result['per_port_generated']) * 64 <= result['logical_region_span_bytes']
        assert sum(r['nand_completed_pages'] for r in timeline) * 16384 == result['counts']['nand_bytes']
        for i, r in enumerate(timeline):
            assert r['t_start_us'] == i * 25 and r['t_end_us'] == (i + 1) * 25
            assert r['cumulative_accepted'] - r['cumulative_completed'] == r['outstanding_end']
            assert 0 <= r['bandwidth_gbps'] <= 256.000001
            assert r['buffer_peak_mib'] <= cfg['buffer_pages'] / 64
            for port in range(4):
                assert r[f'p{port}_cumulative_accepted'] - r[f'p{port}_cumulative_completed'] == r[f'p{port}_outstanding_end']
                assert r[f'p{port}_outstanding_max'] <= cfg['outstanding']
        f, peak = result['windows']['fixed'], result['windows']['peak']
        assert math.isclose(f['completed_bandwidth_gbps'], f['completed_requests'] * 64 / 2000 / 1000)
        rows.append(dict(name=path.parent.name, buffer_mib=cfg['buffer_pages']/64,
                         qd_per_port=cfg['outstanding'], fixed_gbps=f['bandwidth_gbps'],
                         peak_500us_gbps=peak['bandwidth_gbps'], peak_start_us=peak['start_us'],
                         peak_end_us=peak['end_us'], completed_requests=f['completed_requests'],
                         actual_outstanding=f['outstanding_mean'], per_port_outstanding=f['p_outstanding_mean'],
                         per_port_gbps=f['p_bandwidth_gbps'], buffer_mean_mib=f['buffer_mean_mib'],
                         buffer_peak_mib=max(r['buffer_peak_mib'] for r in timeline),
                         nand_gbps=f['nand_completed_gbps'], host_payload_pct=f['host_to_nand_payload_pct'],
                         read_amplification=f['nand_read_amplification'], long_tr_pct=f['long_tr_pct'],
                         tr_counts=f['tr_counts'], second_vs_first_pct=result['windows']['second_vs_first_pct']))
    rows.sort(key=lambda r:(r['buffer_mib'],r['qd_per_port']))
    save(out/'rows.json', rows)
    if rows:
        with (out/'sweep.csv').open('w',newline='') as file:
            writer=csv.DictWriter(file, list(rows[0]), lineterminator='\n');writer.writeheader()
            writer.writerows({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in row.items()} for row in rows)
    save(out/'validation.json',dict(status='passed', cases=len(rows), fixed_window_us=[200,2200],
         sustained_supply=True, source_hashes_verified=True, timeline_accounting_verified=True,
         fixed_device_config_except_qd_and_buffer=True, unchanged_core_model=True,
         core_sha256=digest('znand/model.py'), observation_revisions_verified=True))
    return rows


def run_case(case):
    out, mib, qd, fast = case
    name=f'B_b{mib:g}_q{qd}'
    profile=out/'profiles'/f'{name}.json'
    cfg=read(BASE)|dict(buffer_pages=int(mib*64),outstanding=qd)
    save(profile,cfg)
    destination=out/'cases'/name
    if (destination/'result.json').exists():
        assert read(destination/'result.json')['config'] == cfg
        return name, 'preserved'
    started=time.monotonic()
    command=[sys.executable,'-m','znand.stream64','--pattern','B','--config',str(profile),'--out',str(destination)]
    if fast:command.append('--fast-no-pf-admission')
    result=subprocess.run(command,text=True,capture_output=True)
    if result.returncode:
        raise RuntimeError(name + ': ' + result.stderr)
    save(destination/'execution.json',dict(runtime_seconds=time.monotonic()-started,
         python=platform.python_version(), command=result.args))
    return name, result.stdout.strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT)
    parser.add_argument('--qds',type=int,nargs='+',default=[512,2048,8192,32768])
    parser.add_argument('--buffers',type=float,nargs='+',default=[8.])
    parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--validate-only',action='store_true')
    parser.add_argument('--fast-pf-off','--fast-no-pf-admission',dest='fast_no_pf_admission',action='store_true')
    args=parser.parse_args()
    assert args.workers > 0 and all(q>0 for q in args.qds)
    assert all(m>0 and m*64==int(m*64) for m in args.buffers)
    hashes={p:digest(p) for p in SOURCES}
    hashes[str(BASE)]=digest(BASE)
    snapshot=read(BASE)['snapshot'];hashes[snapshot]=digest(snapshot)
    manifest=dict(workload_schema=2,pattern='B',source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  hashes=hashes,host_request_bytes=64,logical_page_bytes=4096,nand_page_bytes=16384,
                  definition='64 consecutive 64B requests per logical page, then the next page; no address wrap',
                  fixed_window_us=[200,2200],peak_window_us=500,bin_us=25)
    path=args.out/'manifest.json'
    if path.exists():assert read(path)['hashes']==hashes
    else:save(path,manifest)
    if not args.validate_only:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(run_case,(args.out,m,q,args.fast_no_pf_admission)) for m in args.buffers for q in args.qds]
            for future in as_completed(futures):print(*future.result(),flush=True)
    rows=audit(args.out)
    for r in rows:print(f"{r['name']}: {r['fixed_gbps']:.6f} GB/s; QD sum {r['actual_outstanding']:.1f}; buffer mean {r['buffer_mean_mib']:.3f} MiB",flush=True)


if __name__=='__main__':
    main()
