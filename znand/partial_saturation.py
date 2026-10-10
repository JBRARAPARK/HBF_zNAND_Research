"""64B B1/B2 continuous-load observation; the historical A harness is frozen.

Only the Host request size/pattern changes. NAND/controller execution is inherited
unchanged. Data completion timestamps observe the existing full-16KiB transfers.
"""
import math

from .model import Simulator, Input, PAGE, EPS
from .saturation import SaturatedSimulator, logical_index, step_statistics, summarize


class PartialReadSimulator(SaturatedSimulator):
    def __init__(self, config, pattern, region_span, duration_us=2200., start_us=30.):
        assert pattern in ('B1', 'B2')
        assert not config.prefetch and not config.trace
        assert duration_us > 0 and region_span % PAGE == 0
        self.pattern = pattern
        self.region_span = region_span
        self.start_us = start_us
        self.stop_us = start_us + duration_us
        self.sequence = [1] * config.ports
        self.reservations = []
        self.nand_transfers = []
        self.sensing = []
        inputs = [Input(p, (p + 1) * region_span, 64, start_us) for p in range(config.ports)]
        Simulator.__init__(self, config, inputs)
        self.event(self.stop_us, 'observation_complete')

    def replenish(self, port):
        assert not self.sources[port]
        logical = logical_index('A' + self.pattern[1], self.sequence[port])
        assert (logical + 1) * 4096 <= self.region_span, 'Increase the mapped address domain'
        address = (port + 1) * self.region_span + logical * 4096
        key, offset = self.mapper.map(address)
        index = len(self.req)
        self.req.append(dict(port=port, addr=address, size=64, offer=self.now,
                             key=key, offset=offset, lookup=False, accepted=None,
                             ready=None, end=None, head_since=None))
        self.sources[port].append(index)
        self.sequence[port] += 1

    def trace(self, kind, **kw):
        if kind == 'data_start':
            self.nand_transfers.append((self.now + kw['duration'], kw['key']))
        elif kind == 'sense_start':
            self.sensing.append((self.now, kw['tr_kind']))
        super().trace(kind, **kw)


def time_series(sim, bin_us=25.):
    assert all(r['size'] == 64 for r in sim.req)
    start, stop = sim.start_us, sim.stop_us
    count = round((stop - start) / bin_us)
    assert math.isclose(count * bin_us, stop - start, abs_tol=1e-8)
    ports = sim.c.ports
    events = [[] for _ in range(ports)]
    accepted = [[0] * count for _ in range(ports)]
    returned = [[0] * count for _ in range(ports)]
    wire_bytes = [[0.] * count for _ in range(ports)]
    host_bytes_per_us = sim.c.host_bits / 8 * sim.c.host_mhz
    for request in sim.req:
        port = request['port']
        a, b = request['accepted'], request['end']
        if a is not None and a < stop:
            events[port].append((a, 1))
            accepted[port][min(count - 1, int((a - start) / bin_us))] += 1
        if b is not None and b < stop:
            events[port].append((b, -1))
            returned[port][min(count - 1, int((b - start) / bin_us))] += 1
        if 'r_start' in request:
            left = max(start, request['r_start'])
            right = min(stop, b if b is not None else request['r_start'] + request['size'] / host_bytes_per_us)
            while left < right - EPS:
                index = min(count - 1, int((left - start + EPS) / bin_us))
                edge = min(right, start + (index + 1) * bin_us)
                wire_bytes[port][index] += (edge - left) * host_bytes_per_us
                left = edge
    stats = [step_statistics(e, start, bin_us, count) for e in events]
    buffer = step_statistics(sim.reservations, start, bin_us, count)
    cum_a = [0] * ports
    cum_b = [0] * ports
    rows = []
    for index in range(count):
        for port in range(ports):
            cum_a[port] += accepted[port][index]
            cum_b[port] += returned[port][index]
            assert cum_a[port] - cum_b[port] == stats[port]['end'][index]
        row = dict(t_start_us=index * bin_us, t_end_us=(index + 1) * bin_us,
                   bandwidth_gbps=sum(v[index] for v in wire_bytes) / bin_us / 1000,
                   completed_bandwidth_gbps=sum(v[index] for v in returned) * 64 / bin_us / 1000,
                   accepted_requests=sum(v[index] for v in accepted),
                   completed_requests=sum(v[index] for v in returned),
                   cumulative_accepted=sum(cum_a), cumulative_completed=sum(cum_b),
                   outstanding_mean=sum(s['mean'][index] for s in stats),
                   outstanding_end=sum(s['end'][index] for s in stats),
                   buffer_mean_mib=buffer['mean'][index] / 64,
                   buffer_peak_mib=buffer['maximum'][index] / 64)
        for port in range(ports):
            row.update({f'p{port}_accepted': accepted[port][index],
                        f'p{port}_completed': returned[port][index],
                        f'p{port}_cumulative_accepted': cum_a[port],
                        f'p{port}_cumulative_completed': cum_b[port],
                        f'p{port}_gbps': wire_bytes[port][index] / bin_us / 1000,
                        f'p{port}_outstanding_mean': stats[port]['mean'][index],
                        f'p{port}_outstanding_min': stats[port]['minimum'][index],
                        f'p{port}_outstanding_max': stats[port]['maximum'][index],
                        f'p{port}_outstanding_end': stats[port]['end'][index]})
        assert row['bandwidth_gbps'] <= host_bytes_per_us * ports / 1000 + 1e-6
        rows.append(row)
    assert sum(r['accepted_requests'] for r in rows) == sum(r['accepted'] is not None for r in sim.req)
    assert sum(r['completed_requests'] for r in rows) == sim.finished
    assert rows[-1]['outstanding_end'] == sum(map(len, sim.fifo))
    exact_area = sum(min(stop, r['end'] if r['end'] is not None else stop) - r['accepted']
                     for r in sim.req if r['accepted'] is not None)
    assert math.isclose(sum(r['outstanding_mean'] * bin_us for r in rows), exact_area, abs_tol=1e-5)
    completed_bytes = sim.finished * 64
    partial = sum(max(0., min(stop, r['r_start'] + r['size'] / host_bytes_per_us) - r['r_start']) * host_bytes_per_us
                  for r in sim.req if r['end'] is None and 'r_start' in r)
    assert math.isclose(sum(r['bandwidth_gbps'] * bin_us * 1000 for r in rows),
                        completed_bytes + partial, abs_tol=.02)
    transfers = [0] * count
    sensing = [{k: 0 for k in ('first', 'short', 'mid', 'long', 'group')} for _ in range(count)]
    for time, _key in sim.nand_transfers:
        if start <= time < stop:
            transfers[min(count - 1, int((time - start) / bin_us))] += 1
    for time, kind in sim.sensing:
        if start <= time < stop:
            sensing[min(count - 1, int((time - start) / bin_us))][kind] += 1
    assert sum(transfers) == sim.count['nand_bytes'] // PAGE
    for index, row in enumerate(rows):
        row.update(nand_completed_pages=transfers[index],
                   nand_completed_gbps=transfers[index] * PAGE / bin_us / 1000)
        row.update({f'tr_{kind}': value for kind, value in sensing[index].items()})
    return rows



def summarize_partial(rows, warmup_us=200., peak_window_us=500.):
    result = summarize(rows, warmup_us, peak_window_us)
    for label in ('fixed', 'peak', 'first_half', 'second_half'):
        window = result[label]
        chosen = [r for r in rows if r['t_start_us'] >= window['start_us'] and r['t_end_us'] <= window['end_us']]
        pages = sum(r['nand_completed_pages'] for r in chosen)
        payload = window['completed_requests'] * 64
        tr = {kind: sum(r[f'tr_{kind}'] for r in chosen) for kind in ('first', 'short', 'mid', 'long', 'group')}
        window.update(nand_completed_pages=pages, nand_completed_gbps=pages * PAGE / window['duration_us'] / 1000,
                      host_miops=window['completed_requests'] / window['duration_us'],
                      host_to_nand_payload_pct=100 * payload / (pages * PAGE) if pages else None,
                      nand_read_amplification=pages * PAGE / payload if payload else None,
                      tr_counts=tr, long_tr_pct=100 * tr['long'] / sum(tr.values()) if sum(tr.values()) else 0.)
    return result
