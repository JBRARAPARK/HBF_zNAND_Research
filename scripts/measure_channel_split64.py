"""Compare 8x8 planes with full/half channel bandwidth against restored 4x16."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict,replace
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import measure_restored64 as base
from znand.model import Config,Mapper,PAGE,Simulator
OUT=ROOT/'results/znand/channel_split64'
PROFILES=ROOT/'configs/channel_split64'
VARIANTS=('full_bw','half_bw')
PATTERNS=('A1','A2','B')
SPAN=65536*4096
read=base.read;save=base.save;digest=base.digest

def profile(variant,pattern):return PROFILES/variant/f'{pattern}.json'
def reference(pattern):return ROOT/'results/znand/restored64'/pattern/'result.json'
def checked(path,value):
    if path.exists():assert read(path)==value,path
    else:save(path,value)

def snapshot(stripe):
    path=OUT/'snapshots'/f's{stripe}.json'
    c=Config(channels=8,planes=8,stripe=stripe);m=Mapper(c);owners={};ranks=defaultdict(int);mapping={}
    for region in range(4):
        for logical in range(65536):
            (ch,pl,q),offset=m.map((region+1)*SPAN+logical*4096)
            packed=(q*c.planes+pl)*c.channels+ch
            if packed in owners:assert owners[packed]==region
            owners[packed]=region
    for packed,region in sorted(owners.items()):
        ch=packed%c.channels;rank=ranks[region,ch];ranks[region,ch]+=1
        mapping[str(packed)]=[ch,region*2+rank%2,rank//2]
    assert len(set(map(tuple,mapping.values())))==len(mapping)
    checked(path,dict(page_bytes=PAGE,model_geometry=c.model_geometry,mapping=mapping,
        logical_region_span_bytes=SPAN,provenance='Same static region placement rule as 4x16: disjoint region Plane groups in every channel; native eight-channel packing'))
    mapped=Mapper(replace(c,snapshot=str(path)));groups=defaultdict(set);offsets=defaultdict(set)
    for region in range(4):
        for logical in range(65536):
            addr=(region+1)*SPAN+logical*4096
            before,off=m.map(addr);after,new_off=mapped.map(addr)
            assert before[0]==after[0] and off==new_off and after[1]//2==region
            groups[region].add(after[:2]);offsets[after].add(new_off)
    assert all(len(g)==16 for g in groups.values())
    assert all(off=={0,4096,8192,12288} for off in offsets.values())
    assert len(set.union(*groups.values()))==64
    Mapper.map.cache_clear()
    return dict(path=str(path.relative_to(ROOT)),sha256=digest(path),mapped_pages=len(mapping),
        same_region_rule=True,injective=True,each_region_uses_all_eight_channels=True,
        planes_per_region=16,planes_per_region_per_channel=2,full_page_offsets_verified=True,
        note='Packing follows eight channels; physical page grouping need not equal the old four-channel snapshot')

def build():
    checks={str(s):snapshot(s) for s in (4096,16384)}
    for v in VARIANTS:
        for p in PATTERNS:
            old=read(reference(p))['config']
            cfg=old|dict(channels=8,planes=8,snapshot=checks[str(old['stripe'])]['path'],
                        io_gbps=old['io_gbps']*(.5 if v=='half_bw' else 1))
            assert {k for k in cfg if cfg[k]!=old[k]}==({'channels','planes','snapshot','io_gbps'} if v=='half_bw' else {'channels','planes','snapshot'})
            Config(**cfg).validate();checked(profile(v,p),cfg)
    checked(OUT/'snapshot_validation.json',checks)

def manifest():
    sources=base.SOURCES+['scripts/measure_channel_split64.py']
    return dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_hashes={s:digest(ROOT/s) for s in sources},
        profile_hashes={str(profile(v,p).relative_to(ROOT)):digest(profile(v,p)) for v in VARIANTS for p in PATTERNS},
        snapshot_hashes={str(p.relative_to(ROOT)):digest(p) for p in (OUT/'snapshots').glob('*.json')},
        reference_hashes={str(reference(p).relative_to(ROOT)):digest(reference(p)) for p in PATTERNS},
        fixed_window_us=[200,2200],admission_policy=Simulator.admission_policy,
        controls='64 total Planes, 8MiB, original QD/tR/availability/seed/host, region placement rule, RR, FIFO CA, PF OFF',
        changes='4x16 to 8x8; native packing and maintenance phases follow new physical indices; full or half per-channel io_gbps',
        equivalence_note='Report measured differences, not bit-identical traces or universal equivalence')

def run(v,p):
    base.OUT=OUT/v;base.profile=lambda pattern:profile(v,pattern)
    base.run(p)

def audit():
    m=read(OUT/'manifest.json');now=manifest()
    assert {k:v for k,v in m.items() if k!='source_commit'}=={k:v for k,v in now.items() if k!='source_commit'}
    flat=[]
    for v in VARIANTS:
        for p in PATTERNS:
            r=read(OUT/v/p/'result.json');rows=read(OUT/v/p/'timeline.json');c=Config(**read(profile(v,p)))
            assert r['config']==asdict(c) and r['admission_policy']=='round_robin'
            assert r['geometry']==dict(channels=8,planes_per_channel=8,total_planes=64)
            assert r['model_sha256']==m['source_hashes']['znand/model.py']
            assert len(rows)==88 and r['peak_buffer_mib']<=8
            assert max(r['per_port_generated'])*(64 if p=='B' else 4096)<=SPAN
            assert r['windows']==(base.summarize_partial if p=='B' else base.summarize)(rows,200.,500.)
            for i,row in enumerate(rows):
                assert (row['t_start_us'],row['t_end_us'])==(i*25,(i+1)*25)
                assert row['cumulative_accepted']-row['cumulative_completed']==row['outstanding_end']
                assert row['buffer_peak_mib']<=8 and 0<=row['bandwidth_gbps']<=256.000001
                for port in range(4):
                    assert row[f'p{port}_cumulative_accepted']-row[f'p{port}_cumulative_completed']==row[f'p{port}_outstanding_end']
                    assert row[f'p{port}_outstanding_max']<=c.outstanding
            f=r['windows']['fixed'];old=read(reference(p))['windows']['fixed']['bandwidth_gbps']
            flat.append(dict(variant=v,pattern=p,qd_per_port=c.outstanding,io_gbps=c.io_gbps,
                aggregate_raw_io_gbps=c.channels*c.io_gbps,reference_gbps=old,gbps=f['bandwidth_gbps'],
                delta_pct=(f['bandwidth_gbps']/old-1)*100,per_port_gbps=f['p_bandwidth_gbps'],
                per_port_outstanding=f['p_outstanding_mean'],second_vs_first_pct=r['windows']['second_vs_first_pct'],
                fixed_nand_gbps=r['fixed_nand_gbps'],sensing_counts=r['fixed_sensing_counts']))
    save(OUT/'summary.json',flat)
    save(OUT/'validation.json',dict(status='passed',cases=len(flat),source_profiles_snapshots_references_verified=True,
        total_planes=64,capacity_qd_accounting_and_domain_verified=True,fixed_window_us=[200,2200]))
    print(__import__('json').dumps(flat,indent=2))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant',choices=VARIANTS);parser.add_argument('--pattern',choices=PATTERNS)
    parser.add_argument('--validate',action='store_true');a=parser.parse_args()
    if a.validate:audit();return
    if a.variant or a.pattern:
        assert a.variant and a.pattern;run(a.variant,a.pattern);return
    build();m=manifest()
    if (OUT/'manifest.json').exists():
        previous=read(OUT/'manifest.json')
        assert {k:v for k,v in previous.items() if k!='source_commit'}=={k:v for k,v in m.items() if k!='source_commit'}
    else:save(OUT/'manifest.json',m)
    def launch(pair):
        v,p=pair
        if (OUT/v/p/'result.json').exists():return
        subprocess.run([sys.executable,'-B',__file__,'--variant',v,'--pattern',p],cwd=ROOT,check=True)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(launch,[(v,p) for v in VARIANTS for p in ('A1','A2')]))
    for v in VARIANTS:launch((v,'B'))
    audit()

if __name__=='__main__':main()
