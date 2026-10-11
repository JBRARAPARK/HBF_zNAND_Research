import unittest

from znand.model import Config, Simulator, workload as legacy_workload
from znand.partial_saturation import PartialReadSimulator, time_series, summarize_partial
from znand.workloads import workload, address_offset, canonical_pattern, ContinuousRead64Simulator


class CurrentWorkloadTests(unittest.TestCase):
    def test_b_covers_page_then_advances_without_duplicate_or_missing_bytes(self):
        requests = workload('B', ports=1, per_port=130)
        base = requests[0].addr
        self.assertEqual([r.addr-base for r in requests], list(range(0, 130*64, 64)))
        self.assertTrue(all(r.size == 64 for r in requests))
        self.assertEqual(requests[63].addr-base, 4032)
        self.assertEqual(requests[64].addr-base, 4096)
        self.assertEqual(requests[128].addr-base, 8192)

    def test_b_and_a1_cover_identical_bytes_at_equal_logical_page_count(self):
        a = workload('A1', ports=1, per_port=128)
        b = workload('B', ports=1, per_port=128*64)
        self.assertEqual([b[i*64].addr for i in range(128)], [r.addr for r in a])
        self.assertEqual(sum(r.size for r in a), sum(r.size for r in b))

    def test_c_names_preserve_legacy_traces_and_results(self):
        cfg = Config(prefetch=False, buffer_pages=16, outstanding=16)
        for old,new in [('B1','C1'),('B2','C2'),('B3','C3')]:
            a=legacy_workload(old, per_port=96, overlap=.5)
            b=workload(new, per_port=96, overlap=.5)
            self.assertEqual(a,b)
            self.assertEqual(Simulator(cfg,a).run(),Simulator(cfg,b).run())

    def test_legacy_cli_aliases_warn_and_cannot_be_confused_with_new_b(self):
        for old,new in [('B1','C1'),('B2','C2'),('B3','C3')]:
            with self.assertWarns(FutureWarning):self.assertEqual(canonical_pattern(old),new)
        self.assertEqual(canonical_pattern('B'),'B')

    def test_c_continuous_execution_matches_historical_observer(self):
        cfg=Config(planes=16, outstanding=32, buffer_pages=32, ca_policy='head_locality')
        for old,new in [('B1','C1'),('B2','C2')]:
            a=PartialReadSimulator(cfg,old,4096*4096,200.).run_for_duration()
            b=ContinuousRead64Simulator(cfg,new,4096*4096,200.).run_for_duration()
            self.assertEqual(a.req,b.req)
            self.assertEqual(time_series(a,10.),time_series(b,10.))

    def test_b_continuous_address_and_response_accounting(self):
        for stripe in (4096,16384):
            cfg=Config(planes=16,stripe=stripe,outstanding=128,buffer_pages=16,ca_policy='head_locality')
            sim=ContinuousRead64Simulator(cfg,'B',4096*4096,200.).run_for_duration()
            for port in range(4):
                req=[r for r in sim.req if r['port']==port]
                self.assertGreater(len(req),64)
                self.assertEqual([r['addr']-req[0]['addr'] for r in req],list(range(0,len(req)*64,64)))
            rows=time_series(sim,10.);windows=summarize_partial(rows,40.,50.)
            self.assertEqual(sum(r['completed_requests'] for r in rows),sim.finished)
            self.assertEqual(rows[-1]['outstanding_end'],sum(map(len,sim.fifo)))
            self.assertGreater(windows['fixed']['completed_requests'],0)
            self.assertLessEqual(sim.used_peak,cfg.buffer_pages)

    def test_c3_revisit_offset_is_retained(self):
        self.assertEqual([address_offset('C3',i) for i in range(4)],[0,8192,64,4096])


if __name__=='__main__':unittest.main()
