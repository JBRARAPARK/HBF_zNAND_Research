"""Check the A1 CA/Data factorial with PF-ahead disabled; keep primary selection frozen."""
import csv
import hashlib
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from .scheduling_sweep import original, run_case, spec, SOURCE_FILES
from .validate_results import validate


def main():
    out=Path('results/znand/scheduling_next/interaction');out.mkdir(parents=True,exist_ok=True)
    hashes={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (*SOURCE_FILES, 'znand/scheduling_interaction.py')}
    cases=[]
    for ca in ('locality','head_locality'):
        for data in ('ready','head'):
            config=dict(original('A1'),ca_policy=ca,data_policy=data,pf_ahead_limit=0,head_wait_us=48.64)
            s=spec(f'A1_pf0_ca{ca}_data{data}','interaction','A1',config)
            s['case_id']=len(cases);cases.append(s)
    if (out/'manifest.json').exists():
        prior=json.loads((out/'manifest.json').read_text());assert prior['hashes']==hashes
        assert json.loads((out/'cases.json').read_text())==cases
        assert validate(out/'sweep.csv')==4
        print('already complete',flush=True);return
    (out/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
    rows=[]
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
        for f in as_completed([pool.submit(run_case,s) for s in cases]):
            r=f.result();rows.append(r)
            print(r['name'],r['bandwidth_gbps'],flush=True)
    rows.sort(key=lambda r:r['case_id'])
    prior=list(csv.DictReader(Path('results/znand/head_locality/sweep.csv').open()))
    for r in rows:
        if r['data_policy']!='ready':continue
        base=next(x for x in prior if x['pattern']=='A1' and x['per_port']=='8192' and x['locality_max_bypass']=='32'
                  and x['ca_policy']==r['ca_policy'] and (x['ca_policy']=='locality' or x['head_wait_us']=='48.64'))
        for key in ('bandwidth_gbps','p99_offer_latency_us','mean_return_wait_us','count_tr_long'):
            assert r[key]==float(base[key])
    (out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
    fields=sorted({k for r in rows for k in r})
    with (out/'sweep.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fields,lineterminator='\n');writer.writeheader()
        writer.writerows({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)
    assert validate(out/'sweep.csv')==4
    (out/'manifest.json').write_text(json.dumps(dict(validated_rows=4,hashes=hashes,reference_controls_match=True,
        purpose='Additional A1 PF-OFF factorial to separate PF/Data interaction. Primary 86-case selection remains frozen.'),indent=2)+'\n')


if __name__=='__main__':main()
