"""Convert MQSim precondition export to a labeled, repacked sensitivity snapshot."""
import argparse,csv,json,hashlib
from pathlib import Path

def convert(source,dest,revision):
    rows=list(csv.DictReader(Path(source).open()))
    full=[r for r in rows if int(r['valid_bitmap'])==2**32-1]
    full.sort(key=lambda r:int(r['lpa']))
    mapping={};provenance={};seen=set()
    for i,r in enumerate(full):
        assert int(r['chip'])==0
        ch=int(r['channel']);pl=int(r['die'])*2+int(r['plane'])
        q=int(r['block'])*64+int(r['page'])
        assert 0<=ch<4 and 0<=pl<8 and (ch,pl,q) not in seen
        seen.add((ch,pl,q));mapping[str(i)]=[ch,pl,q];provenance[str(i)]=int(r['lpa'])
    doc=dict(page_bytes=16384,kind='MQSim_preconditioned_repacked',
             upstream_revision=revision,raw_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
             source_rows=len(rows),full_valid_rows=len(full),dropped_partial_rows=len(rows)-len(full),
             conversion='Dense packed-slot index -> sorted fully valid MQSim LPA. channel preserved; plane=die*2+plane; q=block*64+page reinterpreted with zNAND address decoder. Not native zNAND physical geometry.',
             mapping=mapping,source_lpa=provenance)
    Path(dest).write_text(json.dumps(doc,separators=(',',':'))+'\n')
    return {k:v for k,v in doc.items() if k not in ('mapping','source_lpa')}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('dest');p.add_argument('--revision',required=True)
    a=p.parse_args();print(json.dumps(convert(a.source,a.dest,a.revision),indent=2))
