import unittest
from znand.latency import cohort, distribution, measurements, summarize_latency


class LatencyTests(unittest.TestCase):
    def test_nearest_rank_and_mean(self):
        s = distribution(range(1, 1001))
        self.assertEqual(s['mean_us'], 500.5)
        self.assertEqual([s[k] for k in ('p50_us','p95_us','p99_us','p99_9_us','max_us')], [500,950,990,999,1000])

    def test_half_open_acceptance_cohort_retains_late_completions(self):
        requests = [dict(accepted=a, end=e) for a,e in [(None,None),(9,11),(10,12),(19,50),(20,22)]]
        self.assertEqual(cohort(requests,10,20),requests[2:4])

    def test_incomplete_cohort_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError,'remain incomplete'):
            cohort([dict(accepted=11,end=12),dict(accepted=19,end=None)],10,20)

    def test_latency_decomposition_and_port_populations(self):
        r=dict(port=0,offer=1,accepted=2,lookup_start=3,lookup_end=3.5,ready=6,r_start=9,end=10)
        self.assertEqual(measurements(r)['device_latency_us'],8)
        self.assertEqual(measurements(r)['ready_to_host_start_us'],3)
        s=summarize_latency([r,dict(r,port=1,end=11)],2,3)
        self.assertEqual(s['requests'],2)
        self.assertEqual(s['all']['device_latency_us']['mean_us'],8.5)
        self.assertEqual(s['per_port']['1']['device_latency_us']['mean_us'],9)
        self.assertEqual(s['completions_after_cohort_window'],2)


if __name__ == '__main__': unittest.main()
