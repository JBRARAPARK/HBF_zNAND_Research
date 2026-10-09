import unittest
from dataclasses import replace
from znand.model import Config,Mapper,Simulator,Input,workload,address,tr_kind,PAGE

class ZNandTests(unittest.TestCase):
    def base(self,**kw):
        return replace(Config(),ports=1,availability=1.,trace=True,**kw)
    def sim(self,rs,c=None):
        s=Simulator(c or self.base(),rs);s.run();return s
    def test_geometry_boundaries(self):
        self.assertEqual(address(24),(0,419,0,0,0))
        self.assertEqual(address(10104),(1,420,0,0,0))
        self.assertEqual(len({address(i) for i in range(20208)}),20208)
    def test_mapping_packing(self):
        m=Mapper(Config())
        self.assertEqual(m.map(0),((0,0,0),0))
        self.assertEqual(m.map(4*4096),((0,0,0),4096))
        self.assertEqual(m.map(16*4096),((0,1,0),0))
        self.assertEqual(m.map(128*4096),((0,0,1),0))
    def test_stripe16(self):
        m=Mapper(Config(stripe=16384))
        self.assertEqual(m.map(4096),((0,0,0),4096))
        self.assertEqual(m.map(16384),((1,0,0),0))
    def test_latency_classification(self):
        self.assertEqual([tr_kind(a,b) for a,b in [(None,0),(0,1),(1,2),(11,12),(23,24),(1,4),(10103,10104)]],['first','short','mid','mid','mid','long','group'])
    def test_single_read_analytical(self):
        c=self.base();s=self.sim([Input(0,0,64,30)],c)
        expected=.5+.1+20.69+PAGE/(80.1125*1000)+.05+.2+.001
        self.assertAlmostEqual(s.req[0]['end']-30,expected)
    def test_4k_one_lookup_credit(self):
        s=self.sim([Input(0,0,4096,30)])
        self.assertEqual(s.peak,[1]);self.assertEqual(len(s.req),1)
        self.assertAlmostEqual(s.req[0]['end']-s.req[0]['r_start'],.064)
    def test_merge_offsets(self):
        s=self.sim([Input(0,0,64,30),Input(0,64,64,30.001)])
        self.assertEqual(s.count['sensing_reads'],1)
        self.assertEqual(s.count['nand_bytes'],PAGE)
        self.assertEqual(len(s.items),0)
    def test_cross_port_merge(self):
        c=replace(self.base(),ports=2)
        s=self.sim([Input(0,0,64,30),Input(1,64,64,30)],c)
        self.assertEqual(s.count['sensing_reads'],1)
        self.assertEqual(s.results()['host_bytes'],128)
    def test_page_buffer_reuse_after_release(self):
        s=self.sim([Input(0,0,64,30),Input(0,64,64,100)])
        self.assertEqual(s.count['sensing_reads'],1)
        self.assertEqual(s.count['page_buffer_hits'],1)
        self.assertEqual(s.count['nand_bytes'],2*PAGE)
    def test_same_plane_overwrites(self):
        s=self.sim([Input(0,0,64,30),Input(0,128*4096,64,100),Input(0,64,64,150)])
        self.assertEqual(s.count['sensing_reads'],3)
        self.assertEqual(s.count['tr_short'],1)
        self.assertEqual(s.count['tr_long'],1)
    def test_other_plane_keeps_buffer(self):
        s=self.sim([Input(0,0,64,30),Input(0,16*4096,64,100),Input(0,64,64,150)])
        self.assertEqual(s.count['sensing_reads'],2)
        self.assertEqual(s.count['page_buffer_hits'],1)
    def test_port_inorder(self):
        s=self.sim([Input(0,0,64,30),Input(0,4096,64,30.001),Input(0,64,64,30.002)])
        self.assertEqual(sorted(r['end'] for r in s.req),[r['end'] for r in s.req])
    def test_ports_independent(self):
        c=replace(self.base(),ports=2)
        s=self.sim([Input(0,0,4096,30),Input(1,4096,64,30)],c)
        self.assertLess(s.req[1]['end'],s.req[0]['end'])
    def test_one_port_all_channels(self):
        s=self.sim([Input(0,i*4096,64,30+i*.001) for i in range(4)])
        self.assertTrue(all(s.channel_data))
    def test_sca_overlap_and_data_serial(self):
        s=self.sim([Input(0,i*65536,4096,30+i*.001) for i in range(40)])
        data=[x for x in s.log if x['event']=='data_start']
        ca=[x for x in s.log if x['event']=='ca_start']
        self.assertTrue(any(d['time_us'] <= a['time_us'] < d['time_us']+d['duration'] for a in ca for d in data))
        for a,b in zip(data,data[1:]):self.assertGreaterEqual(b['time_us']+1e-9,a['time_us']+a['duration'])
    def test_same_plane_no_overlap(self):
        s=self.sim([Input(0,i*128*4096,64,30+i*.001) for i in range(5)])
        ca=[x for x in s.log if x['event']=='ca_start']
        data=[x for x in s.log if x['event']=='data_start']
        for i in range(1,5):self.assertGreaterEqual(ca[i]['time_us']+1e-9,data[i-1]['time_us']+data[i-1]['duration'])
    def test_maintenance_wait_not_tr_scaling(self):
        c=replace(self.base(),availability=.85,maintenance_sync=True)
        s=self.sim([Input(0,0,64,100)],c)
        ca=next(x for x in s.log if x['event']=='ca_start')
        self.assertAlmostEqual(ca['time_us'],115)
        sense=next(x for x in s.log if x['event']=='sense_start')
        self.assertEqual(sense['duration'],20.69)
    def test_no_deadlock_tiny_buffer_and_revisits(self):
        c=replace(Config(),ports=4,buffer_pages=5,outstanding=32,prefetch=True,trace=False)
        s=Simulator(c,workload(per_port=64,overlap=.5));s.run()
        self.assertEqual(s.finished,256);self.assertLessEqual(s.used_peak,5)
    def test_wrong_prefetch_consumes_resources(self):
        c=replace(self.base(),prefetch=True,accuracy=0,lead_us=20)
        s=self.sim([Input(0,0,64,30)],c)
        self.assertGreater(s.count['nand_bytes'],PAGE)
        self.assertGreater(s.results()['leftover_prefetch_pages'],0)
    def test_deterministic(self):
        c=replace(Config(),prefetch=True,accuracy=.5)
        trace=workload(per_port=64)
        self.assertEqual(Simulator(c,trace).run(),Simulator(c,trace).run())
    def test_no_fractional_return_beats(self):
        c=replace(self.base(),host_bits=1024)
        s=self.sim([Input(0,0,64,30)],c)
        self.assertAlmostEqual(s.req[0]['end']-s.req[0]['r_start'],.001)
    def test_remap_unique(self):
        m=Mapper(Config(remap_fraction=.5))
        keys=[m.map(i*PAGE*4)[0] for i in range(1000)]
        self.assertEqual(len(set(keys)),1000)

if __name__=='__main__':unittest.main()

class ResourceAuditTests(unittest.TestCase):
    def test_no_resource_overlap_and_host_bound(self):
        c=Config(trace=True,prefetch=True,accuracy=.5,outstanding=64)
        s=Simulator(c,workload('B3',per_port=128,overlap=.5));r=s.run()
        for kind in ('ca_start','data_start'):
            for ch in range(4):
                events=[e for e in s.log if e['event']==kind and e['key'][0]==ch]
                for a,b in zip(events,events[1:]):
                    self.assertGreaterEqual(b['time_us']+1e-9,a['time_us']+a['duration'])
        self.assertLessEqual(r['bandwidth_gbps'],256)
        self.assertTrue(0<=r['actual_unavailable_fraction']<=1)
    def test_maintenance_deferred_until_data_done(self):
        c=replace(Config(),ports=1,trace=True,maintenance_sync=True,maintenance_period_us=20.)
        s=Simulator(c,[Input(0,0,64,3)]);s.run()
        tr=next(e for e in s.log if e['event']=='data_start')
        maint=[e for e in s.log if e['event']=='maintenance_start' and e['key']==(0,0) and e['time_us']>10]
        self.assertAlmostEqual(maint[0]['time_us'],tr['time_us']+tr['duration'])
    def test_b3_different_offset(self):
        rs=workload('B3',ports=1,per_port=4)
        self.assertEqual(rs[2].addr-rs[0].addr,64)
        self.assertEqual(rs[1].addr-rs[0].addr,8192)
    def test_all_patterns_progress_at_min_buffer(self):
        for pat in ('A1','A2','B1','B2','B3'):
            for seed in range(3):
                c=Config(buffer_pages=5,outstanding=32,prefetch=True,accuracy=.5,seed=seed)
                s=Simulator(c,workload(pat,per_port=48,overlap=.5,seed=seed))
                s.run();self.assertEqual(s.finished,192)
    def test_random_revisit_progress(self):
        import random
        for seed in range(15):
            rng=random.Random(seed);rs=[]
            for p in range(4):
                for i in range(32):rs.append(Input(p,rng.randrange(32)*4096,64,30+i*.001))
            rs.sort(key=lambda r:(r.offer,r.port))
            s=Simulator(Config(buffer_pages=5,outstanding=16,seed=seed),rs)
            s.run();self.assertEqual(s.finished,128)
    def test_snapshot_rejects_missing_and_duplicate(self):
        import tempfile,json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'snapshot.json';p.write_text(json.dumps({'page_bytes':16384,'mapping':{'0':[0,0,0]}}))
            m=Mapper(Config(snapshot=str(p)))
            self.assertEqual(m.map(0),((0,0,0),0))
            with self.assertRaises(ValueError):m.map(4096)
            p.write_text(json.dumps({'page_bytes':16384,'mapping':{'0':[0,0,0],'1':[0,0,0]}}))
            with self.assertRaises(AssertionError):Mapper(Config(snapshot=str(p)))
