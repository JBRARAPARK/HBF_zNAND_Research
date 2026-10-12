import unittest
from dataclasses import replace
from znand.model import Config,Simulator,Input,workload,PAGE
from znand.reference_model_2b1a831 import Config as OldConfig, Simulator as OldSimulator, workload as old_workload

class LocalityTests(unittest.TestCase):
    def run_case(self,**kwargs):
        c=Config(ports=1,stripe=16384,availability=1.,trace=True,ca_policy='locality',**kwargs)
        stride=4*8*PAGE
        requests=[Input(0,q*stride,64,30.) for q in (0,100,1,101,2)]
        sim=Simulator(c,requests);result=sim.run();return sim,result
    def test_reorders_internal_commands_but_keeps_host_order(self):
        sim,result=self.run_case()
        sequence=[r['key'][2] for r in sim.log if r['event']=='sense_start']
        self.assertEqual(sequence,[0,1,2,100,101])
        self.assertEqual(result['counts']['tr_long'],1)
        self.assertEqual([r['end'] for r in sim.req],sorted(r['end'] for r in sim.req))
    def test_bypass_limit_forces_older_request(self):
        sim,_=self.run_case(locality_max_bypass=1)
        sequence=[r['key'][2] for r in sim.log if r['event']=='sense_start']
        self.assertEqual(sequence[:3],[0,1,100])
    def test_age_limit_forces_fifo_for_this_workload(self):
        sim,_=self.run_case(locality_age_us=0.)
        self.assertEqual([r['key'][2] for r in sim.log if r['event']=='sense_start'],[0,100,1,101,2])
    def test_default_fifo_preserves_original_results(self):
        for pattern in ('A1','A2','B1','B2','B3'):
            for pf in (False,True):
                kw=dict(prefetch=pf,outstanding=32,buffer_pages=64)
                a=Simulator(Config(**kw),workload(pattern,per_port=64)).run()
                b=OldSimulator(OldConfig(**kw),old_workload(pattern,per_port=64)).run()
                self.assertEqual(a.pop('admission_policy'), 'round_robin')
                a.pop('config');b.pop('config');self.assertEqual(a,b)
    def test_demand_precedes_prefetch_and_busy_plane_is_skipped(self):
        c=Config(ports=1,stripe=16384,availability=1.,ca_policy='locality')
        sim=Simulator(c,[Input(0,0,64,100.)])
        sim.req[0]['lookup']=True
        pf=dict(key=(0,0,1),eligible=0.,refs=set(),seq=1)
        demand=dict(key=(0,0,99),eligible=0.,refs={0},seq=2)
        sim.plane[(0,0)]['last']=0
        best,_=sim.ca_candidates([pf,demand]);self.assertIs(best[0][1],demand)
        sim.plane[(0,0)]['busy']=True
        self.assertEqual(sim.ca_candidates([pf,demand])[0],{})
    def test_locality_progress_and_shared_resources(self):
        for planes in (8,16):
            c=Config(planes=planes,ca_policy='locality',buffer_pages=8,outstanding=32,prefetch=True,accuracy=.5,trace=True)
            sim=Simulator(c,workload('B3',per_port=64,overlap=.5));sim.run()
            self.assertEqual(sim.finished,256)
            for p in range(4):
                ends=[r['end'] for r in sim.req if r['port']==p];self.assertEqual(ends,sorted(ends))
            for kind in ('ca_start','data_start'):
                for ch in range(4):
                    events=[e for e in sim.log if e['event']==kind and e['key'][0]==ch]
                    for a,b in zip(events,events[1:]):self.assertGreaterEqual(b['time_us']+1e-9,a['time_us']+a['duration'])
    def test_group_boundary_is_not_local(self):
        c=Config(ports=1,ca_policy='locality',availability=1.)
        sim=Simulator(c,[Input(0,0,64,100.)]);sim.plane[(0,0)]['last']=10103
        old=dict(key=(0,0,5),eligible=0.,refs=set(),seq=1)
        following=dict(key=(0,0,10104),eligible=0.,refs=set(),seq=2)
        best,_=sim.ca_candidates([old,following]);self.assertIs(best[0][1],old)

if __name__=='__main__':unittest.main()
