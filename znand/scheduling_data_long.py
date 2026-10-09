"""Resolve A1's faster middle interval but slower full-trace Data-head result."""
import csv
import hashlib
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from .scheduling_sweep import run_case, spec, SOURCE_FILES
from .validate_results import validate


def main():
    root=Path('results/znand/scheduling_next');out=root/'data_long';out.mkdir(parents=True,exist_ok=True)
    hashes={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (*SOURCE_FILES,'znand/scheduling_data_long.py')}
    primary=json.loads((root/'rows.json').read_text())
    primary_cases={s['name']:s for s in json.loads((root/'cases.json').read_text())}
    rows=[];cases=[]
    for variant in ('baseline','candidate'):
        name=f'check_A1_long_{variant}'
        base=next(r for r in primary if r['name']==name)
        cfg=primary_cases[name]['config'];assert cfg['data_policy']=='ready'
        pair=f"A1_long_pf{cfg['pf_ahead_limit']}"
        for data in ('ready','head'):
            s=spec(f'{pair}_data{data}','data_long','A1',dict(cfg,data_policy=data),16384,pair,data)
            s.update(case_id=len(cases),source='reused_primary' if data=='ready' else 'new',source_case=name)
            cases.append(s)
            if data=='ready':
                assert all(base[k]==v for k,v in cfg.items())
                r=dict(base);r.update({k:v for k,v in s.items() if k!='config'});rows.append(r)
    if (out/'manifest.json').exists():
        saved=json.loads((out/'manifest.json').read_text());assert saved['hashes']==hashes
        assert json.loads((out/'cases.json').read_text())==cases
        assert validate(out/'sweep.csv')==4
        print('already complete',flush=True);return
    (out/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
        for f in as_completed([pool.submit(run_case,s) for s in cases if s['source']=='new']):
            r=f.result();rows.append(r);print(r['name'],r['bandwidth_gbps'],flush=True)
    rows.sort(key=lambda r:r['case_id'])
    (out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
    fields=sorted({k for r in rows for k in r})
    with (out/'sweep.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fields,lineterminator='\n');writer.writeheader()
        writer.writerows({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)
    assert validate(out/'sweep.csv')==4
    (out/'manifest.json').write_text(json.dumps(dict(validated_rows=4,new_runs=2,reused_rows=2,hashes=hashes,
        purpose='16384 requests/port with Data head ON; exact primary OFF controls reused. Primary candidate stays frozen.'),indent=2)+'\n')


if __name__=='__main__':main()
