import json
import tempfile
import unittest
from pathlib import Path

from znand.diagnostics import DiagnosticSimulator, intersection_duration, merge_intervals
from znand.model import Config, Input, Mapper, PAGE, Simulator, workload


class PlaneExpansionTests(unittest.TestCase):
    def test_supported_geometry(self):
        for planes in (8, 16):
            Config(planes=planes).validate()
        for planes in (0, 9, 32, 16.):
            with self.assertRaises(AssertionError):
                Config(planes=planes).validate()

    def test_full_round_packing_and_offsets(self):
        for planes in (8, 16):
            for stripe in (4096, 16384):
                mapper = Mapper(Config(planes=planes, stripe=stripe))
                keys = set()
                for logical in range(16*planes):
                    key, offset = mapper.map(logical*4096)
                    keys.add(key)
                    self.assertIn(offset, (0,4096,8192,12288))
                self.assertEqual(keys, {(ch,pl,0) for ch in range(4) for pl in range(planes)})
                self.assertEqual(mapper.map(4*planes*PAGE)[0], (0,0,1))
        self.assertEqual(Mapper(Config(planes=16, stripe=16384)).map(0x80000), ((0,8,0),0))
        self.assertEqual(Mapper(Config(planes=8, stripe=16384)).map(0x80000), ((0,0,1),0))

    def test_high_plane_has_independent_page_buffer(self):
        config = Config(ports=1, planes=16, stripe=16384, availability=1.)
        sim = Simulator(config, [Input(0,0,64,30),Input(0,0x80000,64,100),Input(0,64,64,150)])
        sim.run()
        self.assertEqual(len(sim.plane), 64)
        self.assertEqual(sim.count['sensing_reads'], 2)
        self.assertEqual(sim.count['page_buffer_hits'], 1)

    def test_ordering_and_shared_channel_resources(self):
        config = Config(planes=16, stripe=16384, availability=1., trace=True)
        requests = [Input(n%4,n*PAGE,4096,30.+n*.001) for n in range(128)]
        sim = Simulator(config, requests)
        result = sim.run()
        for port in range(4):
            ends = [r['end'] for r in sim.req if r['port'] == port]
            self.assertEqual(ends, sorted(ends))
        for kind in ('ca_start', 'data_start'):
            for channel in range(4):
                events = [x for x in sim.log if x['event']==kind and x['key'][0]==channel]
                for first, second in zip(events, events[1:]):
                    self.assertGreaterEqual(second['time_us']+1e-9, first['time_us']+first['duration'])
        self.assertLessEqual(result['bandwidth_gbps'], 256.)

    def test_tiny_buffer_progress(self):
        for pattern in ('A1','A2','B1','B2','B3'):
            config = Config(planes=16, buffer_pages=5, outstanding=32, prefetch=True, accuracy=.5)
            sim = Simulator(config, workload(pattern,per_port=48,overlap=.5))
            sim.run()
            self.assertEqual(sim.finished, 192)
            self.assertLessEqual(sim.used_peak, 5)

    def test_snapshot_geometry_is_explicit_for_64_planes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'snapshot.json'
            doc = {'page_bytes':PAGE, 'mapping':{'0':[0,0,0]}}
            path.write_text(json.dumps(doc))
            Mapper(Config(snapshot=str(path)))
            with self.assertRaises(ValueError):
                Mapper(Config(planes=16,snapshot=str(path)))
            doc['model_geometry'] = {'channels':4,'planes_per_channel':16}
            doc['mapping']['0'] = [0,8,0]
            path.write_text(json.dumps(doc))
            self.assertEqual(Mapper(Config(planes=16,snapshot=str(path))).map(0), ((0,8,0),0))

    def test_diagnostics_preserve_behavior_and_account_for_time(self):
        config = Config(planes=16, stripe=16384, prefetch=True, outstanding=32)
        requests = workload('A2', per_port=64)
        plain = Simulator(config, requests).run()
        measured = DiagnosticSimulator(config, requests).run()
        for key, value in plain.items():
            self.assertEqual(measured[key], value)
        metrics = measured['diagnostics']
        for port in range(4):
            self.assertAlmostEqual(sum(metrics[key][port] for key in (
                'host_busy_pct','host_idle_head_data_pct','host_idle_no_accepted_pct','host_idle_lookup_pct')), 100.)
        self.assertEqual(merge_intervals([(1,3),(2,4),(5,5)]), [(1,4)])
        self.assertEqual(intersection_duration([(1,4)], [(2,3),(4,6)]), 1.)


if __name__ == '__main__':
    unittest.main()
