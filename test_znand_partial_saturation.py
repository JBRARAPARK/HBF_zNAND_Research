import math
import unittest

from znand.model import Config, Simulator, PAGE, workload
from znand.partial_saturation import PartialReadSimulator, time_series, summarize_partial


class NoTransferObservation(PartialReadSimulator):
    def trace(self, kind, **kw):
        Simulator.trace(self, kind, **kw)


class PartialSaturationTests(unittest.TestCase):
    def config(self, **kwargs):
        return Config(planes=16, ca_policy='head_locality', **kwargs)

    def test_matches_original_b_addresses_and_64b_payloads(self):
        length = 4096
        for pattern in ('B1', 'B2'):
            sim = PartialReadSimulator(self.config(outstanding=32), pattern,
                                       length * 4096, duration_us=200.).run_for_duration()
            expected = workload(pattern, 4, length, 0., 1000., 7)
            for port in range(4):
                requests = [r for r in sim.req if r['port'] == port]
                original = [r for r in expected if r.port == port]
                self.assertEqual([(r['addr'], r['size']) for r in requests],
                                 [(r.addr, r.size) for r in original[:len(requests)]])
                self.assertTrue(all(r['addr'] % 4096 == 0 and r['size'] == 64 for r in requests))

    def test_64b_accounting_outstanding_order_and_nand_transfers(self):
        sim = PartialReadSimulator(self.config(outstanding=32), 'B2',
                                   4096 * 4096, duration_us=200.).run_for_duration()
        rows = time_series(sim, 10.)
        windows = summarize_partial(rows, 40., 50.)
        self.assertEqual(sum(r['completed_requests'] for r in rows), sim.finished)
        self.assertAlmostEqual(sum(r['completed_bandwidth_gbps'] * 10 * 1000 for r in rows), sim.finished * 64)
        self.assertEqual(sum(r['nand_completed_pages'] for r in rows) * PAGE, sim.count['nand_bytes'])
        self.assertEqual(rows[-1]['outstanding_end'], sum(map(len, sim.fifo)))
        for r in rows:
            self.assertEqual(r['cumulative_accepted'] - r['cumulative_completed'], r['outstanding_end'])
        for label in ('fixed', 'peak'):
            w = windows[label]
            self.assertAlmostEqual(w['host_miops'] * .064, w['completed_bandwidth_gbps'])
            self.assertGreater(w['nand_read_amplification'], 1.)
        self.assertTrue(all(len(q) == 1 for q in sim.sources))
        self.assertTrue(any(r['accepted'] is not None and r['end'] is None for r in sim.req))

    def test_observation_does_not_change_device_execution(self):
        for pattern in ('B1', 'B2'):
            c = self.config(outstanding=64, buffer_pages=48)
            a = PartialReadSimulator(c, pattern, 4096 * 4096, duration_us=200.).run_for_duration()
            b = NoTransferObservation(c, pattern, 4096 * 4096, duration_us=200.).run_for_duration()
            self.assertEqual(a.req, b.req)
            self.assertEqual(a.count, b.count)
            self.assertEqual(a.finished, b.finished)
            self.assertEqual(a.reservations, b.reservations)


if __name__ == '__main__':
    unittest.main()
