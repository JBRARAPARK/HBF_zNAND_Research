"""Current performance baseline: 4 channels x 16 planes, round-robin admission."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from znand.model import Config, Simulator, PAGE
from znand.saturation import SaturatedSimulator,time_series,summarize
from znand.read64_observation import NoPrefetchCapacitySimulator,time_series as series64
from znand.partial_saturation import summarize_partial
OUT=ROOT/'results/znand/restored64'
PATTERNS=('A1','A2','B')
SOURCES=['znand/model.py','znand/run.py','znand/saturation.py','znand/partial_saturation.py',
         'znand/read64_observation.py','znand/workloads.py','scripts/measure_restored64.py']
read=lambda p:json.loads(Path(p).read_text())
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def profile(pattern):return ROOT/'configs/performance64'/f'{pattern}.json'
def reference(pattern):return ROOT/'results/znand/placement_qd_crosscheck'/f'{pattern}_fifo/result.json'

class ObservedA(SaturatedSimulator):
    def __init__(self,*args,**kwargs):
        self.sensing=[];self.nand_transfers=[]
        super().__init__(*args,**kwargs)
    def trace(self,kind,**kw):
        if kind=='data_start':self.nand_transfers.append((self.now+kw['duration'],kw['key']))
        elif kind=='sense_start':self.sensing.append((self.now,kw['tr_kind']))
        super().trace(kind,**kw)

def manifest():
    configs={p:read(profile(p)) for p in PATTERNS}
    for p,cfg in configs.items():
        assert cfg==read(reference(p))['config']
        c=Config(**cfg)
        assert (c.channels,c.planes,c.dies,c.channels_per_die)==(4,16,0,0)
        assert c.buffer_pages==512 and c.ca_policy=='fifo' and not c.prefetch
    return dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_hashes={p:digest(ROOT/p) for p in SOURCES},
        config_hashes={str(profile(p).relative_to(ROOT)):digest(profile(p)) for p in PATTERNS},
        reference_hashes={str(reference(p).relative_to(ROOT)):digest(reference(p)) for p in PATTERNS},
        snapshot_hashes={c['snapshot']:digest(ROOT/c['snapshot']) for c in configs.values()},
        admission_policy=Simulator.admission_policy,geometry=dict(channels=4,planes_per_channel=16,total_planes=64),
        fixed_window_us=[200,2200],warmup_us=200,duration_us=2200,bin_us=25,
        historical_config_identical=True,note='Restore pre-DIE performance profiles; preserve production round-robin admission')

def run(pattern):
    assert not (OUT/pattern/'result.json').exists(),'Preserve previous measurements'
    started=time.monotonic();c=Config(**read(profile(pattern)))
    span=read(ROOT/c.snapshot)['logical_region_span_bytes']
    a=pattern!='B';sim=(ObservedA if a else NoPrefetchCapacitySimulator)(c,pattern,span,2200.)
    pump=sim.pump;next_time=sim.start_us+500
    def progress():
        nonlocal next_time
        if sim.now>=next_time:
            print(pattern,round(sim.now-sim.start_us),'/2200us',flush=True);next_time=sim.now+500
        return pump()
    sim.pump=progress;sim.run_for_duration()
    rows=(time_series if a else series64)(sim,25.)
    windows=(summarize if a else summarize_partial)(rows,200.,500.)
    sensing=Counter(kind for t,kind in sim.sensing if sim.start_us+200<=t<sim.stop_us)
    transfers=[key for t,key in sim.nand_transfers if sim.start_us+200<=t<sim.stop_us]
    result=dict(pattern=pattern,config=asdict(c),admission_policy=sim.admission_policy,
        geometry=dict(channels=c.channels,planes_per_channel=c.planes,total_planes=c.channels*c.planes),
        windows=windows,fixed_sensing_counts=dict(sensing),fixed_nand_gbps=len(transfers)*PAGE/2000/1000,
        per_port_generated=sim.sequence,logical_region_span_bytes=span,peak_buffer_mib=sim.used_peak/64,
        counts=dict(sim.count),model_sha256=digest(ROOT/'znand/model.py'),runtime_seconds=time.monotonic()-started)
    save(OUT/pattern/'timeline.json',rows);save(OUT/pattern/'result.json',result)
    print('DONE',pattern,windows['fixed']['bandwidth_gbps'],windows['fixed']['p_bandwidth_gbps'],flush=True)

def audit():
    m=read(OUT/'manifest.json');current=manifest()
    assert {k:v for k,v in m.items() if k!='source_commit'}=={k:v for k,v in current.items() if k!='source_commit'}
    assert m['admission_policy']=='round_robin'
    summary=[]
    for p in PATTERNS:
        r=read(OUT/p/'result.json');rows=read(OUT/p/'timeline.json');c=Config(**read(profile(p)))
        assert r['config']==asdict(c) and r['admission_policy']=='round_robin'
        assert r['model_sha256']==m['source_hashes']['znand/model.py']
        assert r['geometry']==m['geometry']
        assert len(rows)==88 and r['peak_buffer_mib']<=8
        assert max(r['per_port_generated'])*(64 if p=='B' else 4096)<=r['logical_region_span_bytes']
        assert r['windows']==(summarize_partial if p=='B' else summarize)(rows,200.,500.)
        for i,row in enumerate(rows):
            assert (row['t_start_us'],row['t_end_us'])==(i*25,(i+1)*25)
            assert row['cumulative_accepted']-row['cumulative_completed']==row['outstanding_end']
            assert row['buffer_peak_mib']<=8 and 0<=row['bandwidth_gbps']<=256.000001
            for port in range(4):
                assert row[f'p{port}_cumulative_accepted']-row[f'p{port}_cumulative_completed']==row[f'p{port}_outstanding_end']
                assert row[f'p{port}_outstanding_max']<=c.outstanding
        w=r['windows'];f=w['fixed']
        summary.append(dict(pattern=p,qd_per_port=c.outstanding,gbps=f['bandwidth_gbps'],
            historical_fixed_admission_gbps=read(reference(p))['windows']['fixed']['bandwidth_gbps'],
            per_port_gbps=f['p_bandwidth_gbps'],per_port_outstanding=f['p_outstanding_mean'],
            second_vs_first_pct=w['second_vs_first_pct'],peak_500us_gbps=w['peak']['bandwidth_gbps'],
            long_sensing_count=r['fixed_sensing_counts'].get('long',0),above_200=f['bandwidth_gbps']>200))
    save(OUT/'summary.json',summary)
    save(OUT/'validation.json',dict(status='passed',cases=len(summary),source_config_snapshot_reference_hashes_verified=True,
        original_profiles_restored=True,round_robin_admission=True,capacity_qd_and_port_accounting_verified=True,
        all_above_200=all(s['above_200'] for s in summary),fixed_window_us=[200,2200]))
    print(json.dumps(summary,indent=2))

def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=OUT);parser.add_argument('--case',choices=PATTERNS)
    parser.add_argument('--validate',action='store_true');args=parser.parse_args();OUT=args.out.resolve()
    if args.validate:audit();return
    if args.case:run(args.case);return
    m=manifest()
    if (OUT/'manifest.json').exists():
        old=read(OUT/'manifest.json')
        assert {k:v for k,v in old.items() if k!='source_commit'}=={k:v for k,v in m.items() if k!='source_commit'}
    else:save(OUT/'manifest.json',m)
    def launch(p):
        if (OUT/p/'result.json').exists():return
        subprocess.run([sys.executable,'-B',__file__,'--out',str(OUT),'--case',p],cwd=ROOT,check=True)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(launch,('A1','A2')))
    launch('B')  # Large 64-byte traces run alone to bound peak memory.
    audit()

if __name__=='__main__':main()
