"""Separate bypass tuning from aged FIFO-head priority, then check transferability."""
import argparse
import csv
import hashlib
import json
import math
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from .model import Config, Simulator, workload
from .diagnostics import merge_intervals, intersection_duration
from .validate_results import validate


def run_case(spec):
    c = Config(**spec['config'])
    sim = Simulator(c, workload(spec['pattern'], ports=c.ports, per_port=spec['per_port'],
                               overlap=0., host_mhz=c.host_mhz, seed=c.seed))
    result = sim.run()
    row = {k: v for k, v in spec.items() if k != 'config'}
    row.update(asdict(c))
    row.update({k: v for k, v in result.items() if k not in ('counts', 'config')})
    row.update({'count_'+k: v for k, v in result['counts'].items()})
    row['host_cap_gbps'] = c.ports*c.host_bits/8*c.host_mhz/1000
    quant99 = lambda values: sorted(values)[math.ceil(len(values)*.99)-1]
    row['p99_offer_latency_us'] = quant99([r['end']-r['offer'] for r in sim.req])
    head_wait = [max(0., r['ready']-max(r['head_since'], r['lookup_end'])) for r in sim.req]
    row['p99_head_data_wait_us'] = quant99(head_wait)
    row['mean_head_data_wait_us'] = sum(head_wait)/len(head_wait)
    port_completion, port_p99, port_hol = [], [], []
    for port in range(c.ports):
        requests = [r for r in sim.req if r['port'] == port]
        assert [r['end'] for r in requests] == sorted(r['end'] for r in requests)
        port_completion.append(max(r['end'] for r in requests)-min(r['offer'] for r in requests))
        port_p99.append(quant99([r['end']-r['offer'] for r in requests]))
        head_intervals = merge_intervals((max(r['head_since'], r['lookup_end']), r['ready']) for r in requests)
        ready_intervals = merge_intervals((max(r['ready'], r['lookup_end']), r['r_start']) for r in requests)
        # The head is not ready, so ready work during these intervals is later work.
        port_hol.append(intersection_duration(head_intervals, ready_intervals)/result['elapsed_us']*100)
    row.update(port_completion_us=port_completion, port_p99_offer_us=port_p99,
               port_idle_while_later_ready_pct=port_hol,
               mean_port_idle_while_later_ready_pct=sum(port_hol)/c.ports,
               slowest_port_p99_offer_us=max(port_p99))
    return row


def core_specs():
    specs = []
    for pattern, stripe in (('A1', 4096), ('A2', 16384)):
        for bypass in (4, 8, 16, 32):
            for policy, threshold in [('locality', 12.16)]+[('head_locality', t) for t in (0., 12.16, 48.64)]:
                c = Config(ports=4, stripe=stripe, buffer_pages=2048, outstanding=2048,
                           prefetch=True, ca_policy=policy, locality_max_bypass=bypass, head_wait_us=threshold)
                specs.append(dict(case_id=len(specs), phase='core', pattern=pattern, per_port=8192,
                                  overlap=0., buffer_mib=32, config=asdict(c)))
    return specs


def choose_head(rows):
    core = [r for r in rows if r['phase'] == 'core']
    reference = {p: next(r for r in core if r['pattern'] == p and r['ca_policy'] == 'locality'
                        and int(r['locality_max_bypass']) == 8) for p in ('A1', 'A2')}
    choices = []
    for bypass in (4, 8, 16, 32):
        for threshold in (0., 12.16, 48.64):
            pair = [r for r in core if r['ca_policy'] == 'head_locality'
                    and int(r['locality_max_bypass']) == bypass and float(r['head_wait_us']) == threshold]
            assert len(pair) == 2
            score = math.sqrt(math.prod(float(r['bandwidth_gbps'])/float(reference[r['pattern']]['bandwidth_gbps']) for r in pair))
            tail = max(float(r['p99_offer_latency_us'])/float(reference[r['pattern']]['p99_offer_latency_us']) for r in pair)
            choices.append(dict(bypass=bypass, head_wait_us=threshold, geometric_throughput_ratio=score, worst_p99_ratio=tail))
    # Maximize A1/A2 geometric throughput; p99 is an explicit tie-break and reported tradeoff.
    return max(choices, key=lambda r:(r['geometric_throughput_ratio'], -r['worst_p99_ratio'], -r['bypass'], -r['head_wait_us']))


def followup_specs(selected, start):
    policies = [('locality', 8, 12.16), ('head_locality', selected['bypass'], selected['head_wait_us'])]
    if selected['bypass'] != 8:policies.append(('locality', selected['bypass'], 12.16))
    specs = []
    # Freeze the A1/A2-selected policy before new patterns and longer traces.
    for phase, patterns, length in (('small_read_check', [('B1', 4096), ('B2', 4096), ('B3', 16384)], 8192),
                                    ('long_trace_check', [('A1', 4096), ('A2', 16384)], 16384)):
        for pattern, stripe in patterns:
            for policy, bypass, threshold in policies:
                c = Config(ports=4, stripe=stripe, buffer_pages=2048, outstanding=2048,
                           prefetch=True, ca_policy=policy, locality_max_bypass=bypass, head_wait_us=threshold)
                specs.append(dict(case_id=start+len(specs), phase=phase, pattern=pattern, per_port=length,
                                  overlap=0., buffer_mib=32, config=asdict(c)))
    return specs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--out', default='results/znand/head_locality')
    args = parser.parse_args()
    assert args.workers > 0
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    model_hash = hashlib.sha256(Path('znand/model.py').read_bytes()).hexdigest()
    runner_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    specs = core_specs(); rows = []
    if (out/'sweep.csv').exists():
        checkpoint = json.loads((out/'checkpoint.json').read_text())
        assert checkpoint['model_sha256'] == model_hash and checkpoint['runner_sha256'] == runner_hash
        rows = list(csv.DictReader((out/'sweep.csv').open()))
    if (out/'selection.json').exists():
        specs += followup_specs(json.loads((out/'selection.json').read_text()), len(specs))
    seen = set()
    for row in rows:
        cid = int(row['case_id']); assert cid not in seen; seen.add(cid)
        spec = specs[cid]
        for k, v in spec.items():
            if k != 'config':assert str(row[k]) == str(v), (cid, k)
        for k, v in spec['config'].items():assert str(row[k]) == str(v), (cid, k)
    def save():
        keys = sorted({k for row in rows for k in row})
        with (out/'sweep.tmp').open('w', newline='') as file:
            writer = csv.DictWriter(file, keys, lineterminator='\n'); writer.writeheader()
            for row in sorted(rows, key=lambda r:int(r['case_id'])):
                writer.writerow({k:json.dumps(v) if isinstance(v, (dict, list)) else v for k,v in row.items()})
        (out/'sweep.tmp').replace(out/'sweep.csv')
        (out/'checkpoint.json').write_text(json.dumps(dict(model_sha256=model_hash, runner_sha256=runner_hash,
                                                          saved_rows=len(rows), planned_rows=len(specs)), indent=2))
        (out/'cases.json').write_text(json.dumps(specs, indent=2))
    previous = list(csv.DictReader(Path('results/znand/buffer_growth/sweep.csv').open()))
    def check_reference(row):
        if row['phase'] != 'core' or row['ca_policy'] != 'locality' or row['locality_max_bypass'] != 8:return
        prior = next(r for r in previous if r['pattern'] == row['pattern'] and r['buffer_mib'] == '32' and r['outstanding'] == '2048')
        # Check all prior core scalar metrics and counters, not just throughput.
        for k in prior:
            if k.startswith(('count_', 'mean_', 'p99_', 'p95_')) or k in ('bandwidth_gbps', 'elapsed_us', 'requests', 'host_bytes', 'buffer_peak_pages', 'peak_outstanding'):
                assert float(prior[k] or 0) == float(row.get(k) or 0), (k, prior[k], row.get(k))
    def execute(batch):
        done = {int(r['case_id']) for r in rows}
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(run_case, spec): spec for spec in batch if spec['case_id'] not in done}
            for future in as_completed(pending):
                row = future.result(); check_reference(row); rows.append(row); save()
                print(row['phase'], row['pattern'], row['ca_policy'], row['locality_max_bypass'], row['head_wait_us'],
                      round(row['bandwidth_gbps'], 3), round(row['p99_offer_latency_us'], 2), f'{len(rows)}/{len(specs)}', flush=True)
    started = time.monotonic(); save()
    execute(specs[:32])
    selected = choose_head(rows)
    if len(specs) == 32:specs += followup_specs(selected, len(specs))
    else:assert selected == json.loads((out/'selection.json').read_text())
    (out/'selection.json').write_text(json.dumps(selected, indent=2)); save()
    print('selected head policy', json.dumps(selected), flush=True)
    execute(specs[32:])
    checked = validate(out/'sweep.csv')
    assert checked == len(specs)
    (out/'manifest.json').write_text(json.dumps(dict(validated_rows=checked, model_sha256=model_hash, runner_sha256=runner_hash,
        source_commit='17e7d52', prior_model_sha256=hashlib.sha256(Path('znand/reference_model_17e7d52.py').read_bytes()).hexdigest(),
        last_execution_seconds=time.monotonic()-started, reference_controls_match=True,
        scope='4 ports, 32 planes, shared 32MiB, QD2048/port, PF ON, seed7; core A1/A2 8192 requests/port, bypass4/8/16/32, locality and head waits0/12.16/48.64us. Frozen candidate checks B1/B2/B3 and longer A1/A2 traces.'), indent=2))
    print('complete', checked, flush=True)


if __name__ == '__main__':main()
