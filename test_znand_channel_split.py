import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from znand.model import Config,Input,Mapper,PAGE,Simulator
from znand.workloads import workload,ContinuousRead64Simulator
from znand.read64_observation import NoPrefetchCapacitySimulator,time_series


class ChannelSplitTests(unittest.TestCase):
    def test_flat_eight_channels_keep_sixty_four_planes_and_full_page_packing(self):
        for stripe in (4096,16384):
            c=Config(channels=8,planes=8,stripe=stripe);c.validate();m=Mapper(c)
            slots={}
            for i in range(256):
                key,off=m.map(i*4096);slots.setdefault(key,set()).add(off)
            self.assertEqual(set(slots),{(ch,pl,0) for ch in range(8) for pl in range(8)})
            self.assertTrue(all(v=={0,4096,8192,12288} for v in slots.values()))
            self.assertEqual(m.map(64*PAGE),((0,0,1),0))
        for channels,planes in ((8,4),(8,16),(4,4)):
            with self.assertRaises(AssertionError):Config(channels=channels,planes=planes).validate()

    def test_new_geometry_rejects_undeclared_and_wrong_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'map.json';c=Config(channels=8,planes=8,snapshot=str(path))
            doc=dict(page_bytes=PAGE,mapping={'0':[7,7,0]})
            for geometry in (None,dict(channels=4,planes_per_channel=16)):
                if geometry:doc['model_geometry']=geometry
                path.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):Mapper(c)
            doc['model_geometry']=c.model_geometry;path.write_text(json.dumps(doc))
            self.assertEqual(Mapper(c).map(0),((7,7,0),0))

    def test_eight_independent_paths_and_half_bandwidth_transfer_duration(self):
        for bw in (80.1125,40.05625):
            c=Config(channels=8,planes=8,stripe=PAGE,availability=1.,trace=True,io_gbps=bw)
            sim=Simulator(c,[Input(ch%4,ch*PAGE,64,30.) for ch in range(8)])
            sim.run();events=[e for e in sim.log if e['event']=='data_start']
            self.assertEqual(len(sim.plane),64)
            self.assertEqual({e['key'][0] for e in events},set(range(8)))
            self.assertLess(max(e['time_us'] for e in events),min(e['time_us']+e['duration'] for e in events))
            for e in events:self.assertAlmostEqual(e['duration'],PAGE/(bw*1000)+c.turnaround_us)

    def test_small_buffer_progress_and_fast_engine_equivalence(self):
        c=Config(channels=8,planes=8,buffer_pages=8,outstanding=128,io_gbps=40.05625)
        for pattern in ('A1','A2','B','C1','C2','C3'):
            sim=Simulator(c,workload(pattern,per_port=32,overlap=.5));sim.run()
            self.assertEqual(sim.finished,128);self.assertLessEqual(sim.used_peak,8)
        for pattern in ('B','C1'):
            a=ContinuousRead64Simulator(c,pattern,65536*4096,120.).run_for_duration()
            b=NoPrefetchCapacitySimulator(c,pattern,65536*4096,120.).run_for_duration()
            self.assertEqual(a.req,b.req);self.assertEqual(a.count,b.count)
            self.assertEqual(a.reservations,b.reservations)
            self.assertEqual(time_series(a,10.),time_series(b,10.))


if __name__=='__main__':unittest.main()
