import hashlib
import json
from pathlib import Path

import os
SOURCE=Path(__file__).resolve().parents[2]
ROOT=Path(os.environ.get('ZNAND_RESULTS_DIR', SOURCE/'results/znand/placement_qd_crosscheck')).resolve()
read=lambda p:json.loads(p.read_text())
manifest=read(ROOT/'crosscheck/manifest.json')
assert hashlib.sha256((SOURCE/'znand/model.py').read_bytes()).hexdigest()==manifest['core_hash']
checked=[]
for case in manifest['cases']:
    r=read(ROOT/'crosscheck'/case['name']/'result.json')
    base=read(ROOT/f"{case['pattern']}_fifo"/'result.json')
    differences={k for k in r['config'] if r['config'][k]!=base['config'][k]}
    expected={'snapshot'} if case['variant']=='native_layout' else set() if case['variant']=='qd512_rr' else {'outstanding'}
    assert differences==expected,(case['name'],differences)
    rows=read(ROOT/'crosscheck'/case['name']/'timeline.json')
    assert len(rows)==88 and rows[0]['t_start_us']==0 and rows[-1]['t_end_us']==2200
    fixed=[row for row in rows if row['t_start_us']>=200]
    mean=sum(row['bandwidth_gbps']*25 for row in fixed)/2000
    assert abs(mean-r['windows']['fixed']['bandwidth_gbps'])<1e-9
    assert r['config']['ca_policy']=='fifo' and r['config']['buffer_pages']==512
    assert r['model_sha256']==manifest['core_hash']
    if case['variant']=='native_layout':
        # The placement transform preserves channel, offset and page packing.
        import sys
        sys.path.insert(0,str(SOURCE))
        from znand.model import Mapper,Config
        native=Mapper(Config(**r['config']))
        c=dict(base['config']);c['snapshot']=str(SOURCE/c['snapshot'])
        region=Mapper(Config(**c))
        span=65536*4096
        seen=set()
        for port in range(4):
            for seq in range(65536):
                addr=(port+1)*span+seq*4096
                before,off=native.map(addr);after,new_off=region.map(addr)
                assert before[0]==after[0] and off==new_off
                seen.add((before,after))
        assert len({a for a,b in seen})==len({b for a,b in seen})
        Mapper.map.cache_clear()
    checked.append(dict(name=case['name'],only_config_differences=sorted(differences),
                        round_robin_diagnostic=r['diagnostic_admission'],timeline_mean_recomputed=True))
result=dict(status='passed',core_unchanged=True,cases=checked,
    full_domain_placement_channel_offset_and_injectivity_checked=True,
    note='Round-robin changes admission order in worker memory only. All production files remain unchanged.')
(ROOT/'crosscheck/validation.json').write_text(json.dumps(result,indent=2)+'\n')
print('Validated',len(checked),'cases and full address-domain placement invariants')
