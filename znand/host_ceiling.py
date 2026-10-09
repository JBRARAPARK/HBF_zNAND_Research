"""Separate physical supply bounds, counterfactual timing and static L2P locality."""
import argparse
import csv
import json
import math
import multiprocessing
import subprocess
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .model import Config, Mapper, PAGE, workload
from .pf_qd_sweep import digest, read, save, compatible
from .scheduling_sweep import SOURCE_FILES, run_case, spec
from .validate_results import validate

ROOT=Path('results/znand/host_ceiling')
REFERENCE=Path('results/znand/pf_qd')
SOURCE=(*SOURCE_FILES,'znand/pf_qd_sweep.py','znand/host_ceiling.py')


def base(pattern,planes):
    return dict(read(REFERENCE/f'profiles/{pattern}_host_only.json'),planes=planes)


def region_snapshot(config,pattern,path):
    """Static address-region placement; each region still spans all channels."""
    c=Config(**config);mapper=Mapper(c);owners=defaultdict(set)
    inputs=workload(pattern,ports=c.ports,per_port=8192,overlap=0.,host_mhz=c.host_mhz,seed=c.seed)
    for r in inputs:
        (ch,pl,q),off=mapper.map(r.addr)
        packed=(q*c.planes+pl)*c.channels+ch
        owners[packed].add(r.port)
    per_region=c.planes//c.ports
    assert c.planes%c.ports==0
    ranks=defaultdict(int);mapping={}
    for packed in sorted(owners):
        # A2's final local permutation can cross the next region boundary.
        # Preserve this shared physical page; assign it once to the next region.
        port=max(owners[packed]);ch=packed%c.channels;rank=ranks[port,ch];ranks[port,ch]+=1
        mapping[str(packed)]=[ch,port*per_region+rank%per_region,rank//per_region]
    doc=dict(page_bytes=PAGE,model_geometry=dict(channels=c.channels,planes_per_channel=c.planes),
             mapping=mapping,layout='Static disjoint logical regions use disjoint Plane groups within every channel.',
             provenance='Synthetic layout diagnostic, not MQSim or a dynamic policy. Existing 16KiB packing and offsets retained.')
    if path.exists():assert read(path)==doc
    else:path.write_text(json.dumps(doc,indent=2)+'\n')
    moved=Mapper(Config(**dict(config,snapshot=str(path))))
    assert len({tuple(v) for v in mapping.values()})==len(owners)
    foreign=0
    for r in inputs:
        before,off=mapper.map(r.addr);after,new_off=moved.map(r.addr)
        assert before[0]==after[0] and off==new_off
        packed=(before[2]*c.planes+before[1])*c.channels+before[0]
        assert after[1]//per_region==max(owners[packed])
        foreign+=after[1]//per_region!=r.port
    return dict(pattern=pattern,planes=c.channels*c.planes,mapped_pages=len(mapping),
                same_channel_and_offsets=True,injective_mapping=True,plane_groups_disjoint=True,
                shared_boundary_pages=sum(len(v)>1 for v in owners.values()),cross_region_requests=foreign,
                pages_by_region_channel={f'{p}:{ch}':count for (p,ch),count in sorted(ranks.items())},
                snapshot_sha256=digest(path))


def build(out):
    snapdir=out/'snapshots';snapdir.mkdir(exist_ok=True)
    cases=[];snapshots={}
    for pattern in ('A1','A2'):
        for planes in (8,16):
            cfg=base(pattern,planes);pair=f'{pattern}_{planes*4}Plane'
            snap=snapdir/f'{pair}.json';snapshots[str(snap)]=region_snapshot(cfg,pattern,snap)
            changes=[('baseline',{}),('region_layout',dict(snapshot=str(snap)))]
            if pattern=='A2':
                fast={k+'_us':2. for k in ('first','short','mid','long','group')}
                changes += [('all_tr_2us',fast),('all_tr_2us_no_maintenance',dict(fast,availability=1.))]
            for variant,change in changes:
                s=spec(f'{pair}_{variant}',variant,pattern,dict(cfg,**change),pair=pair,variant=variant)
                s['case_id']=len(cases);cases.append(s)
    return cases,snapshots


def bounds():
    c=Config(**base('A2',8));data=PAGE/(c.io_gbps*1000)+c.turnaround_us
    host=c.ports*c.host_bits/8*c.host_mhz/1000
    channel_data=c.channels*PAGE/data/1000
    lower_first=c.lookup_us+c.ca_us+c.first_us+data+c.ecc_us
    per_port_bytes=8192*4096
    cold=c.ports*per_port_bytes/(per_port_bytes/(host/c.ports*1000)+lower_first)/1000
    array=[]
    for n in (32,64):
        for tr,label in ((c.short_us,'all_short_optimistic'),((c.short_us+c.mid_us)/2,'sequential_short_mid')):
            cycle=c.ca_us+tr+data
            for availability in (.85,1.):
                array.append(dict(planes=n,assumption=label,tr_us=tr,availability=availability,
                                  plane_cycle_us=cycle,array_gbps=n*PAGE*availability/cycle/1000))
    return dict(host_gbps=host,data_service_us=data,data_path_gbps=channel_data,
                required_data_busy_fraction=host/channel_data,
                array=array,minimum_first_ready_us=lower_first,
                cold_host_bound_8192_gbps=cold,
                required_planes_short=host*1000*(c.ca_us+c.short_us+data)/(PAGE*.85),
                required_planes_short_mid=host*1000*(c.ca_us+(c.short_us+c.mid_us)/2+data)/(PAGE*.85),
                allowed_mean_tr_64_us=64*PAGE*.85/(host*1000)-c.ca_us-data,
                note='Array bounds assume fresh data, full 16KiB useful payload, no page re-read, no Data queue wait. 85% is a sustained approximation, not a second discount on measured data.')


def audit(out):
    manifest=read(out/'manifest.json');rows=read(out/'rows.json');cases=read(out/'cases.json')
    assert all(digest(p)==h for p,h in manifest['hashes'].items())
    assert digest(REFERENCE/'rows.json')==manifest['reference_sha256']
    rebuilt,snapshots=build(out);assert rebuilt==cases and snapshots==read(out/'snapshot_validation.json')
    assert bounds()==read(out/'bounds.json')
    assert len(rows)==len(cases)==validate(out/'sweep.csv')==12
    historical={r['name']:r for r in read(REFERENCE/'rows.json')}
    serialized={r['name']:r for r in csv.DictReader((out/'sweep.csv').open())}
    for r in rows:
        s=cases[r['case_id']];Config(**s['config']).validate();assert compatible(r,s)
        assert all(r[k]==v for k,v in s.items() if k!='config')
        assert r['prefetch'] is False and all(v==0 for k,v in r.items() if k.startswith('count_prefetch_'))
        for k,v in r.items():
            assert serialized[r['name']][k]==(json.dumps(v) if isinstance(v,(dict,list)) else str(v))
        if r['source']=='reused':
            previous=historical[r['source_case']]
            for k,v in previous.items():
                if k not in ('case_id','name','stage','pair','variant','source','source_case'):assert r[k]==v
    assert sum(r['source']=='new' for r in rows)==8
    assert len({r['name'] for r in rows})==12
    result=dict(status='passed',conditions=12,new_runs=8,reused_controls=4,
                identical_host_traces=True,static_layout_channel_offset_and_injectivity_verified=True,
                source_hashes_and_serialized_data_verified=True,strict_port_order_checked_in_every_run=True,
                sweep_sha256=digest(out/'sweep.csv'))
    (out/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT);parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--validate-only',action='store_true');args=parser.parse_args()
    if args.validate_only:print(json.dumps(audit(args.out)));return
    out=args.out;out.mkdir(parents=True,exist_ok=True)
    cases,snapshots=build(out)
    assert all(digest(p)==h for p,h in read(REFERENCE/'manifest.json')['hashes'].items())
    metadata=dict(hashes={p:digest(p) for p in SOURCE},reference_sha256=digest(REFERENCE/'rows.json'),
                  source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
    if (out/'checkpoint.json').exists():
        old=read(out/'checkpoint.json');assert old['hashes']==metadata['hashes'] and old['reference_sha256']==metadata['reference_sha256'];metadata=old
    else:(out/'checkpoint.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (out/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
    (out/'snapshot_validation.json').write_text(json.dumps(snapshots,indent=2)+'\n')
    (out/'bounds.json').write_text(json.dumps(bounds(),indent=2)+'\n')
    rows=read(out/'rows.json') if (out/'rows.json').exists() else []
    done={r['name'] for r in rows};reference=read(REFERENCE/'rows.json')
    for s in cases:
        if s['name'] in done:continue
        if s['variant']=='baseline':
            old=next(r for r in reference if compatible(r,s))
            r=dict(old);r.update({k:v for k,v in s.items() if k!='config'})
            r.update(source='reused',source_case=old['name']);rows.append(r);done.add(s['name'])
    save(out,rows);print('exact reused controls',len(rows),flush=True)
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(run_case,s) for s in cases if s['name'] not in done]):
            r=future.result();r.update(source='new',source_case=r['name']);rows.append(r);save(out,rows)
            print(r['name'],round(r['bandwidth_gbps'],4),'GB/s',round(r['middle_bandwidth_gbps'],4),'middle',f'{len(rows)}/12',flush=True)
    (out/'manifest.json').write_text(json.dumps(dict(metadata,new_runs=8,reused_controls=4,validated_rows=12),indent=2)+'\n')
    print(json.dumps(audit(out)),flush=True)


if __name__=='__main__':main()
