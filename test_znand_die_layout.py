import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from znand.model import Config, Input, Mapper, PAGE, Simulator
from znand.workloads import workload
from znand.host_ceiling import region_snapshot


class DieLayoutTests(unittest.TestCase):
    def test_geometry_and_resource_identity(self):
        c = Config.die32()
        c.validate()
        self.assertEqual((c.dies,c.channels_per_die,c.channels,c.planes),(4,2,8,4))
        self.assertEqual(c.topology()['total_planes'],32)
        self.assertEqual({c.channel_index(d,ch) for d in range(4) for ch in range(2)},set(range(8)))
        for changes in ({'channels':4},{'dies':2},{'planes':8},{'channels_per_die':0}):
            with self.assertRaises(AssertionError):replace(c,**changes).validate()
        with self.assertRaises(ValueError):c.channel_index(0,2)
        with self.assertRaises(ValueError):c.channel_index(4,0)
        with self.assertRaises(ValueError):Config().physical_address((0,0,0))

    def test_full_page_packing_both_stripes_and_die_boundaries(self):
        expected={(d,ch,pl,0) for d in range(4) for ch in range(2) for pl in range(4)}
        for stripe in (4096,16384):
            m=Mapper(Config.die32(stripe=stripe))
            slots={}
            for i in range(128):
                key,off=m.map_hierarchical(i*4096)
                slots.setdefault(key,set()).add(off)
            self.assertEqual(set(slots),expected)
            self.assertTrue(all(offsets=={0,4096,8192,12288} for offsets in slots.values()))
            self.assertEqual(m.map_hierarchical(32*PAGE),((0,0,0,1),0))
            step=stripe
            self.assertEqual(m.map_hierarchical(step)[0][:2],(0,1))
            self.assertEqual(m.map_hierarchical(2*step)[0][:2],(1,0))
            self.assertEqual(m.map_hierarchical(7*step)[0][:2],(3,1))
        self.assertEqual(Mapper(Config.die32()).map_hierarchical(8*4096),((0,0,0,0),4096))

    def test_eight_independent_ca_and_data_resources(self):
        c=Config.die32(stripe=PAGE,availability=1.,trace=True)
        inputs=[Input(ch%4,ch*PAGE,64,30.) for ch in range(8)]
        sim=Simulator(c,inputs);result=sim.run()
        self.assertEqual((len(sim.ca),len(sim.data),len(sim.plane)),(8,8,32))
        self.assertEqual(result['channel_nand_bytes'],[PAGE]*8)
        for kind in ('ca_start','data_start'):
            events=[e for e in sim.log if e['event']==kind]
            self.assertEqual({e['key'][0] for e in events},set(range(8)))
            self.assertLess(max(e['time_us'] for e in events),min(e['time_us']+e['duration'] for e in events))
            for event in events:
                self.assertEqual(event['physical_address'],c.physical_address(event['key']))
        self.assertEqual(result['nand_topology'],c.topology())

    def test_shared_channel_serializes_different_planes(self):
        c=Config.die32(stripe=PAGE,availability=1.,trace=True)
        inputs=[Input(i%4,i*8*PAGE,64,30.) for i in range(8)]
        sim=Simulator(c,inputs);sim.run()
        for kind in ('ca_start','data_start'):
            events=[e for e in sim.log if e['event']==kind]
            self.assertEqual({e['key'][0] for e in events},{0})
            for a,b in zip(events,events[1:]):
                self.assertGreaterEqual(b['time_us']+1e-9,a['time_us']+a['duration'])

    def test_same_local_channel_on_other_die_does_not_replace_page_buffer(self):
        c=Config.die32(ports=1,stripe=PAGE,availability=1.,trace=True)
        inputs=[Input(0,0,64,30.),Input(0,2*PAGE,64,100.),Input(0,64,64,150.)]
        sim=Simulator(c,inputs);sim.run()
        self.assertEqual(sim.count['sensing_reads'],2)
        self.assertEqual(sim.count['page_buffer_hits'],1)
        self.assertEqual(sim.plane[(0,0)]['last'],0)
        self.assertEqual(sim.plane[(2,0)]['last'],0)

    def test_new_snapshots_require_full_topology_and_support_die_addresses(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'map.json'
            c=Config.die32(snapshot=str(path))
            doc=dict(page_bytes=PAGE,mapping={'0':[0,0,0]})
            for geometry in (None,{'channels':4,'planes_per_channel':8},{'channels':8,'planes_per_channel':4}):
                if geometry is not None:doc['model_geometry']=geometry
                path.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):Mapper(c)
            doc.update(model_geometry=c.model_geometry,address_format='die_channel_plane_page',mapping={'0':[3,1,2,9]})
            path.write_text(json.dumps(doc))
            m=Mapper(c)
            self.assertEqual(m.map(0),((7,2,9),0))
            self.assertEqual(m.map_hierarchical(0),((3,1,2,9),0))
            doc['mapping']['1']=[4,0,0,0]
            path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError):Mapper(c)

    def test_region_placement_preserves_die_channel_and_offsets(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'region.json'
            c=Config.die32()
            result=region_snapshot(asdict(c),'A1',path)
            self.assertEqual(result['planes'],32)
            self.assertTrue(result['same_channel_and_offsets'])
            self.assertTrue(result['injective_mapping'])
            self.assertEqual(json.loads(path.read_text())['model_geometry'],c.model_geometry)
            Mapper(replace(c,snapshot=str(path)))

    def test_all_workloads_progress_inorder_under_buffer_pressure(self):
        for pattern in ('A1','A2','B','C1','C2','C3'):
            c=Config.die32(buffer_pages=5,outstanding=32,prefetch=True,accuracy=.5)
            sim=Simulator(c,workload(pattern,per_port=64,overlap=.5));r=sim.run()
            self.assertEqual(sim.finished,256)
            self.assertLessEqual(sim.used_peak,5)
            self.assertLessEqual(r['bandwidth_gbps'],256.)
            for port in range(4):
                ends=[req['end'] for req in sim.req if req['port']==port]
                self.assertEqual(ends,sorted(ends))

    def test_cli_defaults_to_flat64_and_explicit_legacy_config_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for legacy in (False,True):
                out=root/str(legacy)
                cmd=[sys.executable,'-B','-m','znand.run','--pattern','A1','--per-port','8','--out',str(out)]
                if legacy:
                    cfg=root/'old.json';cfg.write_text(json.dumps({'channels':4,'planes':8}))
                    cmd+=['--config',str(cfg)]
                subprocess.run(cmd,check=True,capture_output=True)
                r=json.loads((out/'result.json').read_text())
                self.assertEqual(r['config']['channels'],4)
                self.assertEqual(r['config']['planes'],8 if legacy else 16)
                self.assertEqual(r['config']['dies'],0)
                self.assertEqual(r['admission_policy'],'round_robin')
                self.assertNotIn('nand_topology',r)


if __name__=='__main__':unittest.main()
