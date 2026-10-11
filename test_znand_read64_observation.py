import math
import unittest

from znand.model import Config
from znand.workloads import ContinuousRead64Simulator
from znand.read64_observation import NoPrefetchCapacitySimulator, step_statistics, time_series


class ObservationTests(unittest.TestCase):
    def test_sub_epsilon_before_edge_is_counted_in_left_bin(self):
        end=25.-5e-10
        stats=step_statistics([(0.,1),(end,-1)],0.,25.,2)
        self.assertEqual(stats['end'],[0,0])
        self.assertEqual(stats['minimum'],[0,0])
        self.assertAlmostEqual(stats['mean'][0],end/25.,places=14)

    def test_events_on_edge_belong_to_next_bin(self):
        stats=step_statistics([(0.,1),(25.,-1),(25.,1),(50.,-1)],0.,25.,3)
        self.assertEqual(stats['end'],[1,1,0])
        self.assertEqual(stats['mean'],[1.,1.,0.])

    def test_interval_integral_and_endpoint_against_request_definition(self):
        requests=[(0.,25.-5e-10),(25.,50.+5e-10),(25.-5e-10,75.),(3.5,99.)]
        stats=step_statistics([(a,1) for a,b in requests]+[(b,-1) for a,b in requests],0.,25.,4)
        for i in range(4):
            left,right=i*25.,(i+1)*25.
            area=math.fsum(max(0.,min(b,right)-max(a,left)) for a,b in requests)
            self.assertAlmostEqual(stats['mean'][i],area/25.,places=12)
            self.assertEqual(stats['end'][i],sum(a<right and b>=right for a,b in requests))

    def test_fast_capacity_preserves_every_request_timestamp_and_counter(self):
        for pattern,buffer,qd,policy in [('B',5,512,'head_locality'),('B',16,2048,'fifo'),
                                          ('C1',8,128,'head_locality'),('C3',16,128,'head_locality')]:
            cfg=Config(planes=16,outstanding=qd,buffer_pages=buffer,ca_policy=policy)
            original=ContinuousRead64Simulator(cfg,pattern,4096*4096,200.).run_for_duration()
            fast=NoPrefetchCapacitySimulator(cfg,pattern,4096*4096,200.).run_for_duration()
            self.assertEqual(original.req,fast.req)
            self.assertEqual(original.count,fast.count)
            self.assertEqual(original.reservations,fast.reservations)
            self.assertEqual(original.sensing,fast.sensing)
            self.assertEqual(original.nand_transfers,fast.nand_transfers)
            self.assertEqual(time_series(original,25.),time_series(fast,25.))
            self.assertGreater(original.count['buffer_admission_stalls'],0)


if __name__=='__main__':unittest.main()
