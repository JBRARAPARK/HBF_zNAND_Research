import unittest
from dataclasses import replace

from znand.model import Config, Simulator, EPS
from znand.saturation import (SaturatedSimulator, ObservationComplete, step_statistics,
                              time_series, window_summary, logical_index)


class Unobserved(SaturatedSimulator):
    def pump(self):
        if self.now >= self.stop_us - EPS:
            raise ObservationComplete()
        Simulator.pump(self)


class SaturationTests(unittest.TestCase):
    def test_exact_occupancy_integral_and_half_open_bins(self):
        s = step_statistics([(0., 1), (5., 1), (10., -1), (15., -1)], 0., 10., 2)
        self.assertEqual(s['mean'], [1.5, .5])
        self.assertEqual(s['minimum'], [1, 0])
        self.assertEqual(s['maximum'], [2, 1])
        self.assertEqual(s['end'], [2, 0])

    def test_pattern_has_no_finite_trace_wrap(self):
        self.assertEqual([logical_index('A2', i) for i in range(9)], [0, 2, 1, 3, 5, 4, 6, 8, 7])
        self.assertEqual(logical_index('A1', 32768), 32768)

    def test_continuous_supply_qd_and_time_boundary(self):
        c = Config(planes=16, outstanding=16, buffer_pages=128, availability=1., ca_policy='locality')
        sim = SaturatedSimulator(c, 'A2', 4096 * 4096, duration_us=200.).run_for_duration()
        rows = time_series(sim, 10.)
        window = window_summary(rows, 50., 200.)
        self.assertEqual(sim.now, 230.)
        self.assertTrue(all(len(q) == 1 for q in sim.sources))
        self.assertTrue(any(r['end'] is None and r['accepted'] is not None for r in sim.req))
        self.assertGreater(sim.finished, c.outstanding * c.ports)
        self.assertTrue(all(r[f'p{p}_outstanding_max'] <= c.outstanding for r in rows for p in range(4)))
        self.assertEqual(window['p_outstanding_mean'], [16.] * 4)

    def test_small_buffer_tracks_actual_not_configured_outstanding(self):
        c = Config(planes=16, outstanding=128, buffer_pages=5, availability=1., ca_policy='locality')
        sim = SaturatedSimulator(c, 'A1', 4096 * 4096, duration_us=150.).run_for_duration()
        rows = time_series(sim, 10.)
        self.assertLess(max(r['outstanding_mean'] for r in rows), 4 * c.outstanding)
        self.assertTrue(all(r['buffer_peak_mib'] <= 5 / 64 for r in rows))
        self.assertGreater(sim.finished, 0)

    def test_reservation_observation_does_not_change_execution(self):
        for pattern in ('A1', 'A2'):
            c = Config(planes=16, outstanding=32, buffer_pages=40, ca_policy='locality')
            a = SaturatedSimulator(c, pattern, 4096 * 4096, duration_us=200.).run_for_duration()
            b = Unobserved(c, pattern, 4096 * 4096, duration_us=200.).run_for_duration()
            self.assertEqual(a.req, b.req)
            self.assertEqual(a.count, b.count)
            self.assertEqual(a.finished, b.finished)


if __name__ == '__main__':
    unittest.main()
