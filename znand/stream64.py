"""Run current B/C 64B workloads using sustained load and existing device settings."""
import argparse
import csv
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .model import Config
from .partial_saturation import summarize_partial
from .read64_observation import time_series, NoPrefetchCapacitySimulator
from .workloads import ContinuousRead64Simulator, SCHEMA_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--progress-us', type=float, default=0., help='Report simulated progress to stderr; no device events added')
    parser.add_argument('--fast-pf-off', '--fast-no-pf-admission', dest='fast_no_pf_admission', action='store_true', help='Equivalent PF-OFF execution with redundant CPU scans removed')
    parser.add_argument('--pattern', choices=('B', 'C1', 'C2', 'C3'), default='B')
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--duration-us', type=float, default=2200.)
    parser.add_argument('--warmup-us', type=float, default=200.)
    parser.add_argument('--peak-us', type=float, default=500.)
    parser.add_argument('--bin-us', type=float, default=25.)
    parser.add_argument('--domain-pages', type=int, default=65536)
    args = parser.parse_args()
    cfg = Config(**json.loads(args.config.read_text()))
    if cfg.ports != 4 or cfg.prefetch or cfg.trace:
        parser.error('The sustained-load summary uses 4 Ports, prefetch=false and trace=false')
    if args.domain_pages <= 0 or args.bin_us <= 0 or args.peak_us <= 0 or not 0 <= args.warmup_us < args.duration_us:
        parser.error('Invalid observation interval or address domain')
    if args.peak_us > args.duration_us - args.warmup_us:
        parser.error('Peak window exceeds the measured interval')
    for value in (args.duration_us, args.warmup_us, args.peak_us, (args.duration_us + args.warmup_us) / 2):
        if abs(value / args.bin_us - round(value / args.bin_us)) > 1e-8:
            parser.error('Measurement windows must align to bins')
    span = args.domain_pages * 4096
    if cfg.snapshot:
        snapshot = json.loads(Path(cfg.snapshot).read_text())
        span = snapshot.get('logical_region_span_bytes', span)
    if args.out.exists() and any(args.out.iterdir()):
        parser.error('Choose a new output directory to preserve previous measurements')
    simulator = NoPrefetchCapacitySimulator if args.fast_no_pf_admission else ContinuousRead64Simulator
    sim = simulator(cfg, args.pattern, span, args.duration_us)
    if args.progress_us > 0:
        next_progress=sim.start_us+args.progress_us
        original_pump=sim.pump
        def progress_pump():
            nonlocal next_progress
            if sim.now >= next_progress:
                print(f"Simulated {sim.now-sim.start_us:.1f}/{args.duration_us:g} us; completed {sim.finished:,} requests",file=sys.stderr,flush=True)
                next_progress=sim.now+args.progress_us
            return original_pump()
        sim.pump=progress_pump
    sim.run_for_duration()
    rows = time_series(sim, args.bin_us)
    result = dict(workload_schema=SCHEMA_VERSION, pattern=args.pattern,
                  observation_version=2, fast_no_pf_admission=args.fast_no_pf_admission,
                  execution_engine="pf_off_equivalent" if args.fast_no_pf_admission else "reference",
                  config=asdict(cfg), logical_region_span_bytes=span,
                  duration_us=args.duration_us, warmup_us=args.warmup_us, bin_us=args.bin_us,
                  windows=summarize_partial(rows, args.warmup_us, args.peak_us),
                  per_port_generated=sim.sequence, counts=dict(sim.count),
                  outstanding_at_stop=rows[-1]['outstanding_end'],
                  model_sha256=hashlib.sha256(Path(__file__).with_name('model.py').read_bytes()).hexdigest())
    if cfg.dies:
        result['nand_topology'] = cfg.topology()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    (args.out / 'timeline.json').write_text(json.dumps(rows, indent=2) + '\n')
    with (args.out / 'timeline.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps(dict(pattern=args.pattern, fixed_gbps=result['windows']['fixed']['bandwidth_gbps'],
                          mean_outstanding=result['windows']['fixed']['outstanding_mean']), indent=2))


if __name__ == '__main__':
    main()
