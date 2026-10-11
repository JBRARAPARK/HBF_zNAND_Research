"""Current 64B observation: exact half-open bins, independent of device EPS.

Historical observers remain intact. Scheduler/NAND times are never rounded here.
"""
from bisect import bisect_right
from itertools import groupby
import math
import sys

from .model import PAGE, EPS, Simulator
from .workloads import ContinuousRead64Simulator


def step_statistics(events, start, width, count):
    """Integrate occupancy over [left, right); preserve even sub-EPS intervals."""
    groups=((t,sum(delta for _,delta in group)) for t,group in groupby(sorted(events),key=lambda e:e[0]))
    pending=next(groups,None)
    value=0
    while pending and pending[0]<start:
        value+=pending[1];pending=next(groups,None)
    result={key:[] for key in ('mean','minimum','maximum','end')}
    for index in range(count):
        cursor=start+index*width;edge=start+(index+1)*width
        area=0.;minimum=math.inf;maximum=0
        while pending and pending[0]<edge:
            time,delta=pending
            if time>cursor:
                area+=(time-cursor)*value;minimum=min(minimum,value);maximum=max(maximum,value)
            value+=delta
            assert value>=0
            cursor=time;pending=next(groups,None)
        if edge>cursor:
            area+=(edge-cursor)*value;minimum=min(minimum,value);maximum=max(maximum,value)
        result['mean'].append(area/width)
        result['minimum'].append(int(minimum));result['maximum'].append(maximum);result['end'].append(value)
    return result


class NoPrefetchCapacitySimulator(ContinuousRead64Simulator):
    """Equivalent PF-OFF benchmark execution with less Python scheduler work.

Demand items always have at least one accepted reference; the last returned
reference removes the item immediately. Only unused prefetch items can be
unreferenced eviction candidates. With PF disabled that candidate list is empty,
so capacity is exactly the reservation inequality below, without scanning pages.
Redundant dispatch calls are skipped only when no eligible work or NAND
    resource availability can change. CPU work is reduced; admission order,
    counters and device timestamps are kept.
"""
    def dispatch(self):
        # Only the model event handler can change NAND resource availability.
        # AR/timer/Host-R events cannot make NAND work newly issuable. Repeated
        # lookups of an already-eligible demand page cannot do so either.
        # Keep the original dispatch at every NAND/maintenance event and at the
        # first lookup that makes a page eligible; it still chooses every task.
        frame=sys._getframe(1)
        while frame and frame.f_code is not Simulator.run.__code__:
            frame=frame.f_back
        kind=frame.f_locals.get('kind') if frame else None
        datum=frame.f_locals.get('d') if frame else None
        del frame
        if kind in ('timer','wake','returned'):
            return
        if kind=='lookup':
            item=self.items[self.req[datum]['key']]
            if item['eligible'] < self.now-EPS:
                return
        super().dispatch()

    def capacity(self,head=False):
        assert not self.c.prefetch
        reserve=sum(not q and bool(self.sources[p]) for p,q in enumerate(self.fifo))
        if head:reserve=max(0,reserve-1)
        return len(self.items)+1+reserve<=self.c.buffer_pages


def time_series(sim, bin_us=25.):
    assert all(r['size'] == 64 for r in sim.req)
    start, stop = sim.start_us, sim.stop_us
    count = round((stop - start) / bin_us)
    assert math.isclose(count * bin_us, stop - start, abs_tol=1e-8)
    edges = [start + i * bin_us for i in range(count + 1)]
    index_of = lambda t: bisect_right(edges, t) - 1
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
            accepted[port][index_of(a)] += 1
        if b is not None and b < stop:
            events[port].append((b, -1))
            returned[port][index_of(b)] += 1
        if 'r_start' in request:
            left = max(start, request['r_start'])
            right = min(stop, b if b is not None else request['r_start'] + request['size'] / host_bytes_per_us)
            while left < right:
                index = index_of(left)
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
            transfers[index_of(time)] += 1
    for time, kind in sim.sensing:
        if start <= time < stop:
            sensing[index_of(time)][kind] += 1
    assert sum(transfers) == sim.count['nand_bytes'] // PAGE
    for index, row in enumerate(rows):
        row.update(nand_completed_pages=transfers[index],
                   nand_completed_gbps=transfers[index] * PAGE / bin_us / 1000)
        row.update({f'tr_{kind}': value for kind, value in sensing[index].items()})
    return rows
