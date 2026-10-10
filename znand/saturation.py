"""Time-bounded, continuously supplied Host benchmark around the unchanged model.

Device outstanding means accepted AR through final R completion. One next Host
request is always pending per port; the device's existing QD/admission policy
decides whether to accept it. No NAND or controller scheduling policy changes.
"""
import math

from .model import Simulator, Input, PAGE, EPS


class ObservationComplete(Exception):
    pass


class ReservationEvents(dict):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def __setitem__(self, key, value):
        assert key not in self
        super().__setitem__(key, value)
        self.owner.reservations.append((self.owner.now, 1))

    def __delitem__(self, key):
        super().__delitem__(key)
        self.owner.reservations.append((self.owner.now, -1))


def logical_index(pattern, sequence):
    assert pattern in ('A1', 'A2')
    if pattern == 'A1':
        return sequence
    group, position = divmod(sequence, 3)
    return group * 3 + (0, 2, 1)[position]


class SaturatedSimulator(Simulator):
    def __init__(self, config, pattern, region_span, duration_us=2200., start_us=30.):
        assert not config.prefetch and not config.trace
        assert duration_us > 0 and region_span % PAGE == 0
        self.pattern = pattern
        self.region_span = region_span
        self.start_us = start_us
        self.stop_us = start_us + duration_us
        self.sequence = [1] * config.ports
        self.reservations = []
        inputs = [Input(p, (p + 1) * region_span, 4096, start_us) for p in range(config.ports)]
        super().__init__(config, inputs)
        # This external observation event has no device action. pump() stops the
        # benchmark before servicing the boundary; unfinished requests are kept.
        self.event(self.stop_us, 'observation_complete')

    def replenish(self, port):
        assert not self.sources[port]
        logical = logical_index(self.pattern, self.sequence[port])
        assert (logical + 1) * 4096 <= self.region_span, 'Increase the mapped address domain'
        address = (port + 1) * self.region_span + logical * 4096
        key, offset = self.mapper.map(address)
        index = len(self.req)
        self.req.append(dict(port=port, addr=address, size=4096, offer=self.now,
                             key=key, offset=offset, lookup=False, accepted=None,
                             ready=None, end=None, head_since=None))
        self.sources[port].append(index)
        self.sequence[port] += 1

    def admit(self):
        super().admit()
        for port in range(self.c.ports):
            if not self.sources[port]:
                self.replenish(port)
                if len(self.fifo[port]) < self.c.outstanding:
                    self.wake(self.next_ar[port])

    def pump(self):
        if self.now >= self.stop_us - EPS:
            raise ObservationComplete()
        if not isinstance(self.items, ReservationEvents):
            assert not self.items
            self.items = ReservationEvents(self)
        super().pump()

    def run_for_duration(self):
        try:
            super().run()
        except ObservationComplete:
            assert abs(self.now - self.stop_us) < EPS
        else:
            raise AssertionError('Continuous supply ended before the time horizon')
        assert all(len(queue) == 1 for queue in self.sources)
        for port in range(self.c.ports):
            requests = [r for r in self.req if r['port'] == port]
            accepted = [r for r in requests if r['accepted'] is not None]
            returned = [r for r in requests if r['end'] is not None]
            assert len(accepted) - len(returned) == len(self.fifo[port]) <= self.c.outstanding
            assert returned == accepted[:len(returned)]
            previous = 0.
            for request in returned:
                assert request['r_start'] >= previous
                assert request['head_since'] == max(previous, request['accepted'])
                previous = request['end']
        return self


def step_statistics(events, start, width, count):
    """Exact integral and extrema of a piecewise-constant occupancy per bin."""
    area = [0.] * count
    minimum = [math.inf] * count
    maximum = [0] * count
    end_value = [0] * count
    limit = start + width * count
    value, previous = 0, start

    def integrate(left, right, current):
        left, right = max(left, start), min(right, limit)
        while left < right - EPS:
            index = min(count - 1, int((left - start + EPS) / width))
            edge = min(right, start + (index + 1) * width)
            area[index] += current * (edge - left)
            minimum[index] = min(minimum[index], current)
            maximum[index] = max(maximum[index], current)
            end_value[index] = current
            left = edge

    for time, delta in sorted(events):
        if time >= limit:
            break
        integrate(previous, time, value)
        value += delta
        assert value >= 0
        previous = time
    integrate(previous, limit, value)
    return dict(mean=[a / width for a in area], minimum=[int(v) for v in minimum],
                maximum=maximum, end=end_value)


def time_series(sim, bin_us=25.):
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
                   completed_bandwidth_gbps=sum(v[index] for v in returned) * 4096 / bin_us / 1000,
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
    completed_bytes = sim.finished * 4096
    partial = sum(max(0., min(stop, r['r_start'] + r['size'] / host_bytes_per_us) - r['r_start']) * host_bytes_per_us
                  for r in sim.req if r['end'] is None and 'r_start' in r)
    assert math.isclose(sum(r['bandwidth_gbps'] * bin_us * 1000 for r in rows),
                        completed_bytes + partial, abs_tol=.02)
    return rows


def window_summary(rows, start, end):
    chosen = [r for r in rows if r['t_start_us'] >= start and r['t_end_us'] <= end]
    assert chosen and chosen[0]['t_start_us'] == start and chosen[-1]['t_end_us'] == end
    duration = end - start
    weighted = lambda key: sum(r[key] * (r['t_end_us'] - r['t_start_us']) for r in chosen) / duration
    result = dict(start_us=start, end_us=end, duration_us=duration,
                  bandwidth_gbps=weighted('bandwidth_gbps'),
                  completed_bandwidth_gbps=weighted('completed_bandwidth_gbps'),
                  accepted_requests=sum(r['accepted_requests'] for r in chosen),
                  completed_requests=sum(r['completed_requests'] for r in chosen),
                  outstanding_mean=weighted('outstanding_mean'),
                  buffer_mean_mib=weighted('buffer_mean_mib'),
                  outstanding_start=chosen[0]['outstanding_end'] - chosen[0]['accepted_requests'] + chosen[0]['completed_requests'],
                  outstanding_end=chosen[-1]['outstanding_end'],
                  p_outstanding_mean=[weighted(f'p{p}_outstanding_mean') for p in range(4)],
                  p_bandwidth_gbps=[weighted(f'p{p}_gbps') for p in range(4)],
                  p_completed_requests=[sum(r[f'p{p}_completed'] for r in chosen) for p in range(4)])
    assert result['outstanding_end'] - result['outstanding_start'] == result['accepted_requests'] - result['completed_requests']
    return result


def summarize(rows, warmup_us=200., peak_window_us=500.):
    stop = rows[-1]['t_end_us']
    fixed = window_summary(rows, warmup_us, stop)
    candidates = [window_summary(rows, r['t_start_us'], r['t_start_us'] + peak_window_us)
                  for r in rows if r['t_start_us'] >= warmup_us and r['t_start_us'] + peak_window_us <= stop]
    peak = max(candidates, key=lambda r: (r['bandwidth_gbps'], -r['start_us']))
    middle = (warmup_us + stop) / 2
    first, second = window_summary(rows, warmup_us, middle), window_summary(rows, middle, stop)
    return dict(fixed=fixed, peak=peak, first_half=first, second_half=second,
                second_vs_first_pct=(second['bandwidth_gbps'] / first['bandwidth_gbps'] - 1) * 100)
