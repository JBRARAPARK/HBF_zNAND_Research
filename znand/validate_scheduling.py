"""Audit frozen inputs, serialized metrics, selections, controls and provenance."""
import csv
import hashlib
import json
import math
from pathlib import Path
from .model import Config
from .scheduling_sweep import original, select_a, select_b, select_c
from .validate_results import validate


def read(path):return json.loads(path.read_text())
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    root=Path('results/znand/scheduling_next')
    sources={}
    for folder in (root,root/'interaction',root/'data_long'):
        manifest=read(folder/'manifest.json')
        assert all(digest(p)==h for p,h in manifest['hashes'].items())
        rows=read(folder/'rows.json');cases={s['name']:s for s in read(folder/'cases.json')}
        assert len(rows)==len(cases)==manifest['validated_rows']
        assert len({r['name'] for r in rows})==len(rows)
        assert validate(folder/'sweep.csv')==len(rows)
        saved=list(csv.DictReader((folder/'sweep.csv').open()))
        saved={r['name']:r for r in saved}
        for r in rows:
            s=cases[r['name']];Config(**s['config']).validate()
            assert all(r[k]==v for k,v in s.items() if k!='config')
            assert all(r[k]==v for k,v in s['config'].items())
            for k,v in r.items():
                expected=json.dumps(v) if isinstance(v,(dict,list)) else str(v)
                assert saved[r['name']][k]==expected,(r['name'],k)
            components=[v for k,v in r.items() if k.startswith('diag_buffer_mean_') and k!='diag_buffer_mean_total_mib']
            assert all(v>=0 for v in components)
            assert math.isclose(sum(components),r['diag_buffer_mean_total_mib'],rel_tol=1e-10,abs_tol=1e-9)
            assert r['diag_buffer_mean_total_mib']<=r['buffer_mib']+1e-8
            for prefix in ('diag_long_reason_','diag_long_next_'):
                assert sum(v for k,v in r.items() if k.startswith(prefix))==r['diag_long_ca_choices']
            assert sum(v for k,v in r.items() if k.startswith('diag_next_barrier_'))==r.get('diag_long_next_not_accepted',0)
        sources[folder.name]=(rows,cases)
    primary,cases=sources['scheduling_next']
    a,audit=select_a(primary,cases);assert read(root/'selection_A.json')==dict(configs=a,audit=audit)
    b,audit=select_b(primary,cases);assert read(root/'selection_B.json')==dict(configs=b,audit=audit)
    c,audit=select_c(primary,cases,b);assert read(root/'selection_C.json')==dict(configs=c,audit=audit)
    for p in ('A1','A2'):
        assert read(root/f'profiles/candidate_{p}.json')==c[p]
        assert read(root/f'profiles/baseline_{p}.json')==original(p)
    reference=list(csv.DictReader(Path('results/znand/head_locality/sweep.csv').open()))
    controls=[r for r in primary if r['stage']=='A' and r['buffer_pages']==2048 and r['outstanding']==2048]
    controls += [r for r in sources['interaction'][0] if r['data_policy']=='ready']
    for r in controls:
        prior=next(x for x in reference if x['pattern']==r['pattern'] and x['per_port']=='8192'
                   and x['ca_policy']==r['ca_policy'] and x['locality_max_bypass']=='32'
                   and (x['ca_policy']=='locality' or float(x['head_wait_us'])==r['head_wait_us']))
        for k,v in prior.items():
            if k.startswith(('count_','mean_','p99_','p95_','channel_','port_')) or k in ('bandwidth_gbps','elapsed_us','requests','host_bytes','buffer_peak_pages','peak_outstanding','middle_bandwidth_gbps'):
                if v.startswith('['):assert json.loads(v)==r[k],(r['name'],k)
                else:assert float(v or 0)==float(r.get(k) or 0),(r['name'],k)
    byname={r['name']:r for r in primary}
    for r in sources['data_long'][0]:
        if r['source']!='reused_primary':continue
        base=byname[r['source_case']]
        for k,v in base.items():
            if k not in ('case_id','name','stage','pair','variant'):assert r[k]==v,(r['name'],k)
    assert validate(root/'all_results.csv')==92
    combined=list(csv.DictReader((root/'all_results.csv').open()))
    expected=primary+sources['interaction'][0]+[r for r in sources['data_long'][0] if r['source']=='new']
    expected={r['name']:r for r in expected}
    assert len(expected)==len(combined)==92
    assert {r['name'] for r in combined}==set(expected)
    for r in combined:
        base=expected[r['name']]
        assert int(r['source_case_id'])==base['case_id']
        for k,v in base.items():
            if k=='case_id':continue
            assert r[k]==(json.dumps(v) if isinstance(v,(dict,list)) else str(v)),(r['name'],k)
    tests=read(root/'code_validation.json')
    assert tests['status']=='passed' and tests['model_tests']==63
    assert all(digest(p)==h for p,h in tests['hashes'].items())
    assert digest('znand/reference_model_b5c195b.py')=='cebec697da50ce9dba53e0681b5e06a44e9bd8096f20862a2dd5c1cac9b0a15a'
    result=dict(status='passed',new_runs=92,reused_data_long_controls=2,model_tests=63,
                exact_historical_controls=len(controls),frozen_selection_and_profile_audit=True,
                csv_json_and_case_audit=True,buffer_integral_and_long_classification_audit=True,
                hashes={p:digest(p) for p in ('znand/model.py','znand/scheduling_probe.py','znand/scheduling_sweep.py',
                    'znand/scheduling_interaction.py','znand/scheduling_data_long.py','znand/scheduling_report.py',
                    'znand/validate_scheduling.py')},
                all_results_sha256=digest(root/'all_results.csv'))
    (root/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
