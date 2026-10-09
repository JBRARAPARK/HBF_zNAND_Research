"""Reproduce A2 buffer, sensing and 32/64-plane diagnostic experiments."""
import argparse
import csv
import hashlib
import json
import platform
import time
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from pathlib import Path

from .model import Config, Mapper, Simulator, workload
from .sweep import save
from .validate_results import validate

SOURCE_BASE_COMMIT = '2b1a831882dbf23855508c3f5478aadc973d8a23'
CASE_CHANGES = {
    'baseline_8MiB': {},
    'buffer_32MiB': {'buffer_pages': 2048},
    'buffer_32MiB_no_maintenance': {'buffer_pages': 2048, 'availability': 1.},
    'buffer_32MiB_all_tR_2us': {
        'buffer_pages': 2048, 'first_us': 2., 'short_us': 2., 'mid_us': 2.,
        'long_us': 2., 'group_us': 2.,
    },
    '64plane_8MiB': {'planes': 16},
    '64plane_32MiB': {'planes': 16, 'buffer_pages': 2048},
}


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def intersection_duration(left, right):
    i = j = 0
    total = 0.
    while i < len(left) and j < len(right):
        a, b = left[i]
        c, d = right[j]
        total += max(0., min(b, d) - max(a, c))
        if b <= d:
            i += 1
        else:
            j += 1
    return total


class DiagnosticSimulator(Simulator):
    """Read-only instrumentation; issue and response policies are unchanged."""

    def __init__(self, config, inputs):
        self.last_measure_time = None
        self.last_measure_state = Counter()
        self.measured = Counter()
        self.issue_examples = []
        self.issue_causes = Counter()
        self.key_ports = defaultdict(set)
        mapper = Mapper(config)
        for request in inputs:
            self.key_ports[mapper.map(request.addr)[0]].add(request.port)
        super().__init__(config, inputs)

    def trace(self, kind, **kwargs):
        super().trace(kind, **kwargs)
        if kind != 'sense_start':
            return
        key = kwargs['key']
        previous = self.plane[key[:2]]['last']
        previous_ports = self.key_ports.get((key[0], key[1], previous), set())
        current_ports = self.key_ports.get(key, set())
        prior = next(iter(previous_ports)) if len(previous_ports) == 1 else None
        current = next(iter(current_ports)) if len(current_ports) == 1 else None
        if kwargs['tr_kind'] == 'long':
            category = 'long_unknown'
            if prior is not None and current is not None:
                category = 'long_cross_port' if prior != current else 'long_within_port'
            self.issue_causes[category] += 1
        if key[:2] == (0, 0) and len(self.issue_examples) < 20:
            self.issue_examples.append({
                'time_us': self.now, 'previous_q': previous, 'q': key[2],
                'previous_port': prior, 'port': current, 'tr_kind': kwargs['tr_kind'],
            })

    def pump(self):
        if self.last_measure_time is not None:
            delta = max(0., self.now - max(self.measure_start, self.last_measure_time))
            for key, value in self.last_measure_state.items():
                self.measured[key] += delta * value
        else:
            self.measure_start = min(r['offer'] for r in self.req)
        super().pump()
        state = Counter()
        for port in range(self.c.ports):
            if self.rb[port]:
                state[f'port{port}_return_busy_us'] = 1
            elif not self.fifo[port]:
                state[f'port{port}_idle_no_accepted_us'] = 1
            elif not self.req[self.fifo[port][0]]['lookup']:
                state[f'port{port}_idle_lookup_us'] = 1
            else:
                state[f'port{port}_idle_head_data_us'] = 1
        state['buffer_full_us'] = int(len(self.items) == self.c.buffer_pages)
        state['buffer_reserved_page_us'] = len(self.items)
        state['buffer_ready_page_us'] = sum(x['state'] == 'ready' for x in self.items.values())
        self.last_measure_state = state
        self.last_measure_time = self.now

    def results(self):
        result = super().results()
        elapsed = result['elapsed_us']
        diagnostics = {}
        for label, counter in (
            ('host_busy_pct', 'return_busy_us'),
            ('host_idle_head_data_pct', 'idle_head_data_us'),
            ('host_idle_no_accepted_pct', 'idle_no_accepted_us'),
            ('host_idle_lookup_pct', 'idle_lookup_us'),
        ):
            diagnostics[label] = [self.measured[f'port{p}_{counter}']/elapsed*100 for p in range(self.c.ports)]
        diagnostics.update(
            buffer_full_pct=self.measured['buffer_full_us']/elapsed*100,
            buffer_avg_reserved_pages=self.measured['buffer_reserved_page_us']/elapsed,
            buffer_avg_ready_pages=self.measured['buffer_ready_page_us']/elapsed,
        )
        port_metrics = []
        for port in range(self.c.ports):
            requests = [r for r in self.req if r['port'] == port]
            if not requests:
                continue
            previous_end = self.measure_start
            head_wait = []
            for request in requests:
                head_wait.append((max(previous_end, request['accepted']), request['ready']))
                previous_end = request['end']
            ready_wait = merge_intervals((r['ready'], r['r_start']) for r in requests)
            hol_idle = intersection_duration(merge_intervals(head_wait), ready_wait)
            port_metrics.append({
                'port': port, 'last_return_us': max(r['end'] for r in requests),
                'mean_admission_us': sum(r['accepted']-r['offer'] for r in requests)/len(requests),
                'mean_return_wait_us': sum(r['r_start']-r['ready'] for r in requests)/len(requests),
                'idle_while_later_ready_us': hol_idle,
                'idle_while_later_ready_pct': hol_idle/elapsed*100,
            })
        result['diagnostics'] = diagnostics
        result['issue_order'] = {
            'counts': dict(self.issue_causes), 'CH0_PL0_sequence': self.issue_examples,
            'ports': port_metrics,
        }
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='results/znand/diagnostics_2026-10-09')
    parser.add_argument('--per-port', type=int, default=4096)
    parser.add_argument('--cases', nargs='+', choices=tuple(CASE_CHANGES), default=list(CASE_CHANGES))
    args = parser.parse_args()
    if args.per_port < 1:
        parser.error('--per-port must be positive')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = replace(Config(), stripe=16384, outstanding=2048, prefetch=True)
    inputs = workload('A2', ports=4, per_port=args.per_port, overlap=0., host_mhz=base.host_mhz, seed=base.seed)
    results, rows, cases, summary = [], [], [], []
    for case_id, name in enumerate(args.cases):
        config = replace(base, **CASE_CHANGES[name])
        started = time.perf_counter()
        result = DiagnosticSimulator(config, inputs).run()
        result.update(case=name, runtime_seconds=time.perf_counter()-started)
        results.append(result)
        specification = dict(case_id=case_id, phase='diagnostic', pattern='A2', overlap=0., per_port=args.per_port, config=asdict(config))
        cases.append(specification)
        row = {k: v for k, v in result.items() if k not in ('config', 'counts', 'diagnostics', 'issue_order')}
        row.update(asdict(config))
        row.update({k:v for k,v in specification.items() if k != 'config'})
        row.update({'count_'+k:v for k,v in result['counts'].items()})
        row['host_cap_gbps'] = config.ports*config.host_bits/8*config.host_mhz/1000
        rows.append(row)
        counts = result['counts']
        sensing = counts.get('sensing_reads', 0)
        avg_tr = sum(counts.get('tr_'+k, 0)*getattr(config, k+'_us') for k in ('first','short','mid','long','group'))/sensing if sensing else 0.
        short = dict(case=name, planes_total=config.channels*config.planes, buffer_MiB=config.buffer_pages*16384/1024**2,
                     bandwidth_gbps=result['bandwidth_gbps'], mean_latency_us=result['mean_latency_us'],
                     long_pct=counts.get('tr_long',0)/sensing*100 if sensing else 0., average_tr_us=avg_tr)
        summary.append(short)
        (out/'results.json').write_text(json.dumps(results, indent=2))
        print(json.dumps(short), flush=True)
    save(rows, out)
    with (out/'summary.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, list(summary[0]))
        writer.writeheader(); writer.writerows(summary)
    (out/'cases.json').write_text(json.dumps(cases, indent=2))
    checked = validate(out/'sweep.csv')
    manifest = dict(source_base_commit=SOURCE_BASE_COMMIT,
                    model_sha256=hashlib.sha256(Path(__file__).with_name('model.py').read_bytes()).hexdigest(),
                    python=platform.python_version(), checked_rows=checked, accounting_status='passed',
                    pattern='A2', per_port=args.per_port, overlap=0.,
                    note='Locality and response policies unchanged. 2us sensing and zero maintenance are diagnostic assumptions.')
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
