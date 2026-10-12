"""Fixed-window measurements for 4 DIE x 2 channels x 4 planes."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from znand.model import Config, Mapper, PAGE
from znand.saturation import SaturatedSimulator, time_series, summarize
from znand.read64_observation import NoPrefetchCapacitySimulator, time_series as series64
from znand.partial_saturation import summarize_partial

OUT=ROOT/'results/znand/die32_performance'
SPAN=65536*4096
SOURCES=['znand/model.py','znand/saturation.py','znand/partial_saturation.py',
         'znand/read64_observation.py','znand/workloads.py','scripts/measure_die32.py']

def read(p):return json.loads(Path(p).read_text())
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class ObservedA(SaturatedSimulator):
    def __init__(self,*args,**kwargs):
        self.sensing=[];self.nand_transfers=[]
        super().__init__(*args,**kwargs)
    def trace(self,kind,**kw):
        if kind=='data_start':self.nand_transfers.append((self.now+kw['duration'],kw['key']))
        elif kind=='sense_start':self.sensing.append((self.now,kw['tr_kind']))
        super().trace(kind,**kw)

def snapshot(stripe):
    path=OUT/'snapshots'/f'regions_s{stripe}.json'
    c=Config.die32(stripe=stripe);mapper=Mapper(c)
    owners={};mapping={};ranks=defaultdict(int)
    for region in range(4):
        for logical in range(65536):
            (ch,pl,q),off=mapper.map((region+1)*SPAN+logical*4096)
            packed=(q*c.planes+pl)*c.channels+ch
            if packed in owners:assert owners[packed]==region
            owners[packed]=region
    for packed,region in sorted(owners.items()):
        ch=packed%c.channels;rank=ranks[region,ch];ranks[region,ch]+=1
        mapping[str(packed)]=[ch,region,rank]
    assert len(set(map(tuple,mapping.values())))==len(mapping)
    doc=dict(page_bytes=PAGE,model_geometry=c.model_geometry,mapping=mapping,
             logical_region_span_bytes=SPAN,provenance='Static disjoint address regions, one Plane per region in each of eight channels')
    if path.exists():assert read(path)==doc
    else:save(path,doc)
    mapped=Mapper(replace(c,snapshot=str(path)))
    for region in range(4):
        for logical in range(65536):
            addr=(region+1)*SPAN+logical*4096
            before,off=mapper.map(addr);after,off2=mapped.map(addr)
            assert before[0]==after[0] and off==off2 and after[1]==region
    Mapper.map.cache_clear()
    return str(path.relative_to(ROOT))

def cases():
    specs=[]
    for pattern in ('A1','A2'):
        for qd in (128,256,512,1024,2048):
            specs.append(dict(pattern=pattern,layout='region',qd=qd,phase='a'))
        specs.append(dict(pattern=pattern,layout='native',qd=512,phase='a'))
    for pattern in ('C1','C2'):
        specs.append(dict(pattern=pattern,layout='region',qd=512,phase='a'))
    for qd in (512,8192,16384,32768):
        specs.append(dict(pattern='B',layout='region',qd=qd,phase='b'))
    for s in specs:
        s['name']=f"{s['pattern']}_{s['layout']}_q{s['qd']}"
        c=Config.die32(stripe=16384 if s['pattern']=='A2' else 4096,outstanding=s['qd'])
        if s['layout']=='region':c=replace(c,snapshot=f'results/znand/die32_performance/snapshots/regions_s{c.stripe}.json')
        s['config']=asdict(c)
    return specs

def run(spec):
    started=time.monotonic();c=Config(**spec['config']);a=spec['pattern'].startswith('A')
    sim=(ObservedA if a else NoPrefetchCapacitySimulator)(c,spec['pattern'],SPAN,2200.)
    pump=sim.pump;next_time=sim.start_us+500
    def progress():
        nonlocal next_time
        if sim.now>=next_time:
            print(spec['name'],round(sim.now-sim.start_us),'/2200us',flush=True);next_time=sim.now+500
        return pump()
    sim.pump=progress;sim.run_for_duration()
    rows=(time_series if a else series64)(sim,25.)
    windows=(summarize if a else summarize_partial)(rows,200.,500.)
    transfers=[key for t,key in sim.nand_transfers if sim.start_us+200<=t<sim.stop_us]
    sensing=Counter(k for t,k in sim.sensing if sim.start_us+200<=t<sim.stop_us)
    duration=PAGE/(c.io_gbps*1000)+c.turnaround_us
    busy=[0.]*8
    for t,key in sim.nand_transfers:
        busy[key[0]]+=max(0.,min(t,sim.stop_us)-max(t-duration,sim.start_us+200))
    result=dict(**spec,windows=windows,nand_topology=c.topology(),
                fixed_sensing_counts=dict(sensing),fixed_nand_gbps=len(transfers)*PAGE/2000/1000,
                fixed_channel_data_busy_pct=[v/2000*100 for v in busy],
                counts=dict(sim.count),actual_unavailable_fraction=sum(max(0,min(b,sim.stop_us)-max(a,sim.start_us+200))
                  for _,a,b in sim.busy_intervals)/(2000*32),
                per_port_generated=sim.sequence,peak_buffer_mib=sim.used_peak/64,
                runtime_seconds=time.monotonic()-started,model_sha256=digest(ROOT/'znand/model.py'))
    save(OUT/'cases'/spec['name']/'result.json',result)
    save(OUT/'cases'/spec['name']/'timeline.json',rows)
    print('DONE',spec['name'],windows['fixed']['bandwidth_gbps'],windows['fixed']['p_outstanding_mean'],flush=True)

def audit(require_all=True):
    manifest=read(OUT/'manifest.json')
    assert all(digest(ROOT/p)==h for p,h in manifest['source_hashes'].items())
    assert all(digest(ROOT/p)==h for p,h in manifest['snapshot_hashes'].items())
    flat=[]
    for s in cases():
        path=OUT/'cases'/s['name']/'result.json'
        if not path.exists():
            assert not require_all,s['name']
            continue
        r=read(path);rows=read(path.with_name('timeline.json'));c=Config(**r['config'])
        assert r['config']==s['config'] and r['model_sha256']==manifest['source_hashes']['znand/model.py']
        assert r['windows']==(summarize if s['pattern'].startswith('A') else summarize_partial)(rows,200.,500.)
        assert len(rows)==88 and r['peak_buffer_mib']<=8
        assert max(r['per_port_generated'])*(4096 if s['pattern']!='B' else 64)<=SPAN
        for i,row in enumerate(rows):
            assert row['t_start_us']==i*25 and row['t_end_us']==(i+1)*25
            assert row['cumulative_accepted']-row['cumulative_completed']==row['outstanding_end']
            assert 0<=row['bandwidth_gbps']<=256.000001
            assert row['buffer_peak_mib']<=8
            for p in range(4):
                assert row[f'p{p}_cumulative_accepted']-row[f'p{p}_cumulative_completed']==row[f'p{p}_outstanding_end']
                assert row[f'p{p}_outstanding_max']<=c.outstanding
        fixed=r['windows']['fixed'];tr=r['fixed_sensing_counts']
        flat.append(dict(name=s['name'],pattern=s['pattern'],layout=s['layout'],qd=s['qd'],
            gbps=fixed['bandwidth_gbps'],peak_500us_gbps=r['windows']['peak']['bandwidth_gbps'],
            per_port_gbps=fixed['p_bandwidth_gbps'],per_port_outstanding=fixed['p_outstanding_mean'],
            buffer_mean_mib=fixed['buffer_mean_mib'],nand_gbps=r['fixed_nand_gbps'],
            long_pct=100*tr.get('long',0)/sum(tr.values()),
            actual_unavailable_pct=r['actual_unavailable_fraction']*100,
            second_vs_first_pct=r['windows']['second_vs_first_pct']))
    save(OUT/'summary.json',flat)
    if flat:
        with (OUT/'summary.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,list(flat[0]),lineterminator='\n');w.writeheader();w.writerows(flat)
    save(OUT/'validation.json',dict(status='passed' if require_all else 'partial',completed_cases=len(flat),
         expected_cases=len(cases()),source_and_snapshot_hashes_verified=True,
         fixed_window_us=[200,2200],timeline_and_port_accounting_verified=True,
         capacity_and_qd_verified=True,scope='Measured configurations; not a global maximum or hardware result'))
    print(json.dumps(flat,indent=2))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('a','b','all','build','validate','summary'),default='all')
    parser.add_argument('--case');parser.add_argument('--workers',type=int,default=2);args=parser.parse_args()
    if args.case:run(next(s for s in cases() if s['name']==args.case));return
    if args.phase in ('validate','summary'):audit(args.phase=='validate');return
    for stripe in (4096,16384):snapshot(stripe)
    manifest=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_hashes={p:digest(ROOT/p) for p in SOURCES},
        snapshot_hashes={str(p.relative_to(ROOT)):digest(p) for p in (OUT/'snapshots').glob('*.json')},
        common='4DIE x 2 independent Channel x 4Plane, 8MiB, FIFO CA, fixed admission, PF OFF, unchanged tR, 85% nominal availability',
        fixed_window_us=[200,2200],snapshot_validation='full domain channel/offset preservation, injectivity, disjoint Plane ownership')
    if (OUT/'manifest.json').exists():assert read(OUT/'manifest.json')==manifest
    else:save(OUT/'manifest.json',manifest)
    save(OUT/'cases.json',cases())
    if args.phase=='build':return
    selected=[s for s in cases() if args.phase in ('all',s['phase'])]
    def launch(s):
        if (OUT/'cases'/s['name']/'result.json').exists():return
        subprocess.run([sys.executable,'-B',__file__,'--case',s['name']],cwd=ROOT,check=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(launch,selected))
    audit(args.phase=='all')

if __name__=='__main__':main()
