"""Read-only scheduling diagnostics; counters never participate in decisions."""
from collections import Counter, defaultdict
from .model import Simulator, PAGE, address, tr_kind


class ObservedPage(dict):
    def __init__(self, item, owner):
        super().__init__(item)
        self.owner = owner

    def __setitem__(self, key, value):
        if key == 'state' and self.get(key) != value:
            self.owner.change_state(self.get(key), value)
        super().__setitem__(key, value)


class ObservedPages(dict):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def __setitem__(self, key, item):
        assert key not in self
        self.owner.change_state(None, item['state'])
        super().__setitem__(key, ObservedPage(item, self.owner))

    def __delitem__(self, key):
        self.owner.change_state(self[key]['state'], None)
        super().__delitem__(key)


class SchedulingProbe(Simulator):
    def __init__(self, config, inputs):
        self.measure_start = min(r.offer for r in inputs)
        self.area_last = 0.
        self.state_counts = Counter()
        self.state_area = Counter()
        self.long_reasons = Counter()
        self.next_states = Counter()
        self.next_barriers = Counter()
        self.requests_by_key = None
        super().__init__(config, inputs)

    def integrate(self):
        dt = max(0., self.now - max(self.area_last, self.measure_start))
        for state, count in self.state_counts.items():
            self.state_area[state] += count * dt
        self.area_last = self.now

    def change_state(self, old, new):
        self.integrate()
        if old is not None:
            self.state_counts[old] -= 1
            assert self.state_counts[old] >= 0
        if new is not None:self.state_counts[new] += 1

    def pump(self):
        if not isinstance(self.items, ObservedPages):
            assert not self.items
            self.items = ObservedPages(self)
        super().pump()

    def new_item(self, key, pf=False):
        super().new_item(key, pf)
        return self.items[key]

    def ca_candidates(self, waiting):
        best, decisions = super().ca_candidates(waiting)
        if self.requests_by_key is None:
            self.requests_by_key = defaultdict(list)
            for request in self.req:self.requests_by_key[request['key']].append(request)
        # Inspect future requests only AFTER the base scheduler has decided.
        # This is an offline explanation, not scheduler knowledge or lookahead.
        for channel, (_, item) in best.items():
            key = item['key']; plane = self.plane[key[:2]]
            if plane['pb'] == key[2] or tr_kind(plane['last'], key[2]) != 'long':continue
            reason = decisions[channel][2] if channel in decisions else 'fifo'
            self.long_reasons[reason] += 1
            next_key = (*key[:2], plane['last'] + 1)
            nxt = self.items.get(next_key)
            if address(next_key[2])[0] != address(plane['last'])[0]:
                state = 'group_boundary'
            elif nxt is not None:
                if nxt['state'] != 'waiting':state = 'present_' + nxt['state']
                elif nxt['eligible'] is None:state = 'lookup_pending'
                elif self.demand(item) and not self.demand(nxt):state = 'pf_lower_priority'
                else:state = 'eligible_overridden_' + reason
            else:
                requests = self.requests_by_key.get(next_key, [])
                pending = [r for r in requests if r['accepted'] is None]
                if not requests:state = 'outside_trace'
                elif pending:
                    state = 'not_accepted'
                    request = min(pending, key=lambda r:r['offer']); port = request['port']
                    flags = []
                    if request['offer'] > self.now:flags.append('not_offered')
                    if len(self.fifo[port]) >= self.c.outstanding:flags.append('qd_full')
                    if len(self.items) >= self.c.buffer_pages:flags.append('buffer_full')
                    self.next_barriers['_and_'.join(flags) or 'earlier_requests_or_guard'] += 1
                elif all(r['end'] is not None for r in requests):state = 'consumed'
                else:state = 'other'
            self.next_states[state] += 1
        return best, decisions

    def diagnostics(self):
        self.integrate()
        assert sum(self.state_counts.values()) == len(self.items)
        duration = self.now - self.measure_start
        assert sum(self.state_area.values()) <= self.c.buffer_pages * duration + 1e-4
        result = {'diag_long_ca_choices': sum(self.long_reasons.values())}
        for prefix, counts in [('diag_long_reason_', self.long_reasons),
                               ('diag_long_next_', self.next_states),
                               ('diag_next_barrier_', self.next_barriers)]:
            result.update({prefix + k:v for k,v in counts.items()})
        for state in ('waiting', 'ca', 'sensing', 'sensed', 'transfer', 'ecc', 'ready'):
            result['diag_buffer_mean_' + state + '_mib'] = self.state_area[state] / duration * PAGE / 2**20
        result['diag_buffer_mean_total_mib'] = sum(self.state_area.values()) / duration * PAGE / 2**20
        return result
