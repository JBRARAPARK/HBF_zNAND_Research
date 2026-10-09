"""Independent accounting checks on serialized CSV results."""
import csv,json,math
from pathlib import Path

def validate(path):
    rows=list(csv.DictReader(path.open()))
    for r in rows:
        f=lambda k:float(r.get(k) or 0)
        assert f('requests')==f('ports')*f('per_port')
        size=4096 if r['pattern'].startswith('A') else 64
        assert f('host_bytes')==size*f('requests')
        assert 0<f('bandwidth_gbps')<=f('host_cap_gbps')+1e-8
        assert f('inclusive_prefetch_gbps')<=f('bandwidth_gbps')+1e-8
        assert f('buffer_peak_pages')<=f('buffer_pages')
        assert f('peak_outstanding')<=f('outstanding')
        assert 0<=f('actual_unavailable_fraction')<=1
        assert abs(f('mean_offer_latency_us')-f('mean_latency_us')-f('mean_admission_wait_us'))<1e-7
        return_us=math.ceil(size/(f('host_bits')/8))/f('host_mhz')
        decomposed=f('mean_lookup_queue_us')+f('lookup_us')+f('mean_data_wait_us')+f('mean_return_wait_us')+return_us
        assert abs(f('mean_latency_us')-decomposed)<1e-7,(r['case_id'],decomposed,f('mean_latency_us'))
        nb=f('count_nand_bytes');assert nb%16384==0
        scheduled=sum(json.loads(r['channel_nand_bytes']))
        assert 0<=scheduled-nb<=4*16384
        classified=sum(f('count_tr_'+k) for k in ['first','short','mid','long','group'])
        assert 0<=f('count_sensing_reads')-classified<=4
    return len(rows)

def main():
    outputs={}
    for name in ('full','extended'):
        p=Path('results/znand')/name/'sweep.csv'
        if p.exists():outputs[name]=validate(p)
    Path('results/znand/accounting_validation.json').write_text(json.dumps({'status':'passed','checked_rows':outputs},indent=2))
    print(outputs)
if __name__=='__main__':main()
