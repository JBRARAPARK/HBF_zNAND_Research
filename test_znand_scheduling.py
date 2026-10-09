import unittest
from dataclasses import asdict, replace
from znand.model import Config, Input, PAGE, Simulator, workload
from znand.reference_model_b5c195b import Config as PriorConfig, Simulator as PriorSimulator
from znand.scheduling_probe import SchedulingProbe


class SchedulingExtensionTests(unittest.TestCase):
    def ca_fixture(self, **changes):
        c = replace(Config(ports=1, stripe=16384, availability=1., ca_policy='locality',
                           pf_ahead_limit=1), **changes)
        s = Simulator(c, [Input(0, 100*32*PAGE, 64, 100.)])
        demand = s.new_item(s.req[0]['key']); demand['refs'].add(0); demand['eligible'] = 1.
        s.req[0].update(lookup=True, lookup_end=1., accepted=1., head_since=1.)
        s.fifo[0].append(0)
        pf = s.new_item((0, 0, 1), True)
        s.plane[(0, 0)]['last'] = 0; s.now = 10.
        return s, demand, pf

    def test_only_eligible_adjacent_pf_can_cross_demand(self):
        s, demand, pf = self.ca_fixture()
        self.assertIs(s.ca_candidates([demand, pf])[0][0][1], pf)
        pf['key'] = (0, 0, 2)
        self.assertIs(s.ca_candidates([demand, pf])[0][0][1], demand)

    def test_pf_ahead_guardrails(self):
        for guard in ('pf_limit', 'age', 'locality_limit', 'head'):
            s, demand, pf = self.ca_fixture()
            if guard == 'pf_limit':s.pf_ahead_bypasses[(0, 0)] = 1
            if guard == 'age':demand['eligible'] = -2000.
            if guard == 'locality_limit':s.locality_bypasses[(0, 0)] = s.c.locality_max_bypass
            if guard == 'head':s.now = 100.
            self.assertIs(s.ca_candidates([demand, pf])[0][0][1], demand, guard)

    def test_local_demand_precedes_pf_and_group_boundary_is_excluded(self):
        s, demand, pf = self.ca_fixture()
        s.plane[(0, 0)]['pb'] = 100
        self.assertIs(s.ca_candidates([demand, pf])[0][0][1], demand)
        s.plane[(0, 0)].update(pb=None, last=10103); pf['key'] = (0, 0, 10104)
        self.assertIs(s.ca_candidates([demand, pf])[0][0][1], demand)

    def test_pf_counter_changes_on_issue_only_and_demand_resets_it(self):
        s, demand, pf = self.ca_fixture()
        s.ca_candidates([demand, pf])
        self.assertEqual(s.pf_ahead_bypasses[(0, 0)], 0)
        s.dispatch()
        self.assertEqual(s.pf_ahead_bypasses[(0, 0)], 1)
        self.assertEqual(s.locality_bypasses[(0, 0)], 1)
        s.plane[(0, 0)]['busy'] = False; s.ca[0] = False
        s.dispatch()
        self.assertEqual(s.pf_ahead_bypasses[(0, 0)], 0)

    def test_blocked_plane_or_channel_has_no_pf_candidate(self):
        for block in ('busy', 'off', 'ca'):
            s, demand, pf = self.ca_fixture()
            if block == 'ca':s.ca[0] = True
            else:s.plane[(0, 0)][block] = True
            self.assertEqual(s.ca_candidates([demand, pf])[0], {})

    def data_fixture(self, **changes):
        c = replace(Config(ports=1, stripe=16384, availability=1., data_policy='head'), **changes)
        s = Simulator(c, [Input(0, 0, 64, 100.), Input(0, 4*PAGE, 64, 100.)])
        pages = []
        for index in range(2):
            x = s.new_item(s.req[index]['key']); x['refs'].add(index)
            x.update(state='sensed', transfer_ready=5. if index == 0 else 1.)
            s.req[index].update(lookup=True, lookup_end=1., accepted=1., head_since=1. if index == 0 else None)
            s.fifo[0].append(index); pages.append(x)
        s.now = 10.
        return s, *pages

    def test_data_head_precedes_older_ready_follower(self):
        s, head, follower = self.data_fixture()
        self.assertIs(s.data_candidates()[0][0][1], head)
        s.c = replace(s.c, data_policy='ready')
        self.assertIs(s.data_candidates()[0][0][1], follower)

    def test_data_age_guard_and_no_preemption(self):
        s, head, follower = self.data_fixture(data_age_us=8.)
        best, reasons = s.data_candidates()
        self.assertIs(best[0][1], follower); self.assertEqual(reasons[0], 'age')
        s.data[0] = True
        self.assertEqual(s.data_candidates()[0], {})

    def test_data_requires_looked_up_head_and_wait_threshold(self):
        s, head, follower = self.data_fixture(data_head_wait_us=20.)
        self.assertIs(s.data_candidates()[0][0][1], follower)
        s.c = replace(s.c, data_head_wait_us=0.); s.req[0]['lookup'] = False
        self.assertIs(s.data_candidates()[0][0][1], follower)

    def test_disabled_features_and_probe_preserve_prior_metrics(self):
        for pattern in ('A1', 'A2', 'B1', 'B2', 'B3'):
            for policy in ('fifo', 'locality', 'head_locality'):
                options = dict(ca_policy=policy, prefetch=True, outstanding=32, buffer_pages=64)
                inputs = workload(pattern, per_port=64)
                prior = PriorSimulator(PriorConfig(**options), inputs).run(); prior.pop('config')
                for cls in (Simulator, SchedulingProbe):
                    sim = cls(Config(**options), inputs)
                    result = sim.run(); result.pop('config')
                    self.assertEqual(result, prior)
                    if cls is SchedulingProbe:
                        diag = sim.diagnostics()
                        self.assertGreater(diag['diag_buffer_mean_total_mib'], 0.)

    def test_enabled_features_preserve_resources_order_and_progress(self):
        for planes in (8, 16):
            for budget in (1, 2):
                c = Config(planes=planes, ca_policy='head_locality', pf_ahead_limit=budget,
                           data_policy='head', prefetch=True, accuracy=.5, buffer_pages=8,
                           outstanding=32, trace=True)
                sim = SchedulingProbe(c, workload('B3', per_port=96, overlap=.5)); sim.run(); sim.diagnostics()
                self.assertEqual(sim.finished, 384)
                for p in range(4):
                    req = [r for r in sim.req if r['port'] == p]
                    self.assertEqual([r['end'] for r in req], sorted(r['end'] for r in req))
                    for a,b in zip(req, req[1:]):self.assertGreaterEqual(b['r_start'], a['end'])
                for kind in ('ca_start', 'data_start'):
                    for ch in range(4):
                        events = [e for e in sim.log if e['event'] == kind and e['key'][0] == ch]
                        for a,b in zip(events, events[1:]):self.assertGreaterEqual(b['time_us']+1e-9, a['time_us']+a['duration'])

    def test_buffer_state_integral_matches_single_read_timeline(self):
        c = Config(ports=1, availability=1.)
        sim = SchedulingProbe(c, [Input(0, 0, 4096, 30.)]); result = sim.run()
        diag = sim.diagnostics()
        expected = dict(waiting=c.lookup_us, ca=c.ca_us, sensing=c.first_us, sensed=0.,
                        transfer=PAGE/(c.io_gbps*1000)+c.turnaround_us,
                        ecc=c.ecc_us, ready=4096/(c.host_bits/8)/c.host_mhz)
        self.assertAlmostEqual(result['elapsed_us'], sum(expected.values()))
        for state, duration in expected.items():
            self.assertAlmostEqual(diag['diag_buffer_mean_'+state+'_mib'],
                                   duration/result['elapsed_us']*PAGE/2**20)
        self.assertAlmostEqual(diag['diag_buffer_mean_total_mib'], PAGE/2**20)

    def test_invalid_new_settings(self):
        for options in ({'pf_ahead_limit':-1}, {'pf_ahead_limit':1.5}, {'pf_ahead_limit':1},
                        {'data_policy':'bad'}, {'data_age_us':-1}, {'data_head_wait_us':float('nan')},
                        {'pf_head_wait_us':float('inf')}):
            with self.assertRaises(AssertionError):Config(**options).validate()


if __name__ == '__main__':unittest.main()
