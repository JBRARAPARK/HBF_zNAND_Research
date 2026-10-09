import unittest
from dataclasses import replace
from znand.model import Config, Input, PAGE, Simulator, workload
from znand.reference_model_17e7d52 import Config as PriorConfig, Simulator as PriorSimulator


class HeadSchedulingTests(unittest.TestCase):
    def candidates(self, **changes):
        config = replace(Config(ports=1, stripe=16384, availability=1.,
                                ca_policy='head_locality'), **changes)
        sim = Simulator(config, [Input(0, 100*32*PAGE, 64, 100.),
                                 Input(0, 32*PAGE, 64, 100.)])
        head = sim.new_item(sim.req[0]['key'])
        adjacent = sim.new_item(sim.req[1]['key'])
        for index, item in enumerate((head, adjacent)):
            item['refs'].add(index); item['eligible'] = 1.
            sim.req[index].update(lookup=True, lookup_end=1., accepted=0.)
        sim.fifo[0].extend((0, 1)); sim.req[0]['head_since'] = 1.
        sim.plane[(0, 0)]['last'] = 0
        sim.now = 20.
        return sim, head, adjacent

    def test_urgent_head_overrides_adjacent_page(self):
        sim, head, adjacent = self.candidates()
        best, decisions = sim.ca_candidates([head, adjacent])
        self.assertIs(best[0][1], head)
        self.assertEqual(decisions[0][2], 'head')

    def test_age_starts_at_head_and_lookup_completion(self):
        sim, head, adjacent = self.candidates()
        sim.req[0]['head_since'] = 19.
        self.assertIs(sim.ca_candidates([head, adjacent])[0][0][1], adjacent)
        sim.req[0]['head_since'] = 1.; sim.req[0]['lookup_end'] = 19.
        self.assertIs(sim.ca_candidates([head, adjacent])[0][0][1], adjacent)

    def test_unlooked_up_or_inflight_head_is_not_promoted(self):
        sim, head, adjacent = self.candidates()
        sim.req[0]['lookup'] = False
        self.assertEqual(sim.urgent_heads(), {})
        sim.req[0]['lookup'] = True; head['state'] = 'sensing'
        self.assertEqual(sim.urgent_heads(), {})
        head['state'] = 'waiting'; sim.plane[(0, 0)]['busy'] = True
        self.assertEqual(sim.ca_candidates([head, adjacent])[0], {})
        sim.plane[(0, 0)].update(busy=False, off=True)
        self.assertEqual(sim.ca_candidates([head, adjacent])[0], {})

    def test_bypass_and_age_protection_precede_head(self):
        for guard in ('bypass', 'age'):
            sim, head, adjacent = self.candidates()
            adjacent['seq'] = 0
            if guard == 'bypass':sim.locality_bypasses[(0, 0)] = sim.c.locality_max_bypass
            else:sim.now = 1100.; head['eligible'] = 1099.
            self.assertIs(sim.ca_candidates([head, adjacent])[0][0][1], adjacent)

    def test_head_promoted_across_planes_but_aged_demand_protected(self):
        sim, head, adjacent = self.candidates()
        adjacent['key'] = (0, 1, 1); adjacent['seq'] = 0
        self.assertIs(sim.ca_candidates([head, adjacent])[0][0][1], head)
        sim.now = 1100.; head['eligible'] = 1099.
        self.assertIs(sim.ca_candidates([head, adjacent])[0][0][1], adjacent)

    def test_shared_page_uses_oldest_head(self):
        c = Config(ports=2, stripe=16384, availability=1., ca_policy='head_locality')
        sim = Simulator(c, [Input(0, 0, 64, 100.), Input(1, 0, 64, 100.)])
        item = sim.new_item((0, 0, 0)); item['refs'] = {0, 1}
        for p in range(2):
            sim.fifo[p].append(p)
            sim.req[p].update(lookup=True, lookup_end=1., head_since=5.+p*5)
        sim.now = 30.
        self.assertEqual(sim.urgent_heads(), {(0, 0, 0): (5., 0)})

    def test_locality_and_disabled_head_preserve_prior_model(self):
        for pattern in ('A1', 'A2', 'B1', 'B2', 'B3'):
            for pf in (False, True):
                options = dict(ca_policy='locality', prefetch=pf, outstanding=32, buffer_pages=64)
                inputs = workload(pattern, per_port=64)
                prior = PriorSimulator(PriorConfig(**options), inputs).run(); prior.pop('config')
                for c in (Config(**options), replace(Config(**options), ca_policy='head_locality', head_wait_us=1e8)):
                    actual = Simulator(c, inputs).run(); actual.pop('config')
                    self.assertEqual(actual, prior)

    def test_progress_order_resources_and_head_timestamps(self):
        for planes in (8, 16):
            c = Config(planes=planes, ca_policy='head_locality', head_wait_us=0.,
                       locality_max_bypass=4, buffer_pages=8, outstanding=32,
                       prefetch=True, accuracy=.5, trace=True)
            sim = Simulator(c, workload('B3', per_port=64, overlap=.5)); sim.run()
            self.assertEqual(sim.finished, 256)
            self.assertLessEqual(sim.used_peak, c.buffer_pages)
            for p in range(4):
                requests = [r for r in sim.req if r['port'] == p]
                self.assertEqual([r['end'] for r in requests], sorted(r['end'] for r in requests))
                previous_end = 0.
                for r in requests:
                    self.assertEqual(r['head_since'], max(r['accepted'], previous_end))
                    previous_end = r['end']
            for kind in ('ca_start', 'data_start'):
                for ch in range(4):
                    events = [e for e in sim.log if e['event'] == kind and e['key'][0] == ch]
                    for a, b in zip(events, events[1:]):
                        self.assertGreaterEqual(b['time_us']+1e-9, a['time_us']+a['duration'])

    def test_invalid_head_threshold(self):
        for threshold in (-1., float('nan'), float('inf')):
            with self.assertRaises(AssertionError):Config(head_wait_us=threshold).validate()


if __name__ == '__main__':unittest.main()
