from pathlib import Path
import csv,json,time,hashlib
from dataclasses import replace
from znand.model import Config,Simulator,workload

class CappedReservations(Simulator):
    """Diagnostic only: 32MiB physical capacity, original 512-slot admission cap."""
    def capacity(self,head=False):
        physical=self.c
        self.c=replace(physical,buffer_pages=512)
        try:return super().capacity(head=head)
        finally:self.c=physical

def main():
    out=Path('results/znand/buffer_causality');out.mkdir(parents=True,exist_ok=True)
    c=Config(buffer_pages=2048,ports=4,stripe=16384,outstanding=2048,prefetch=True)
    start=time.monotonic()
    result=CappedReservations(c,workload('A2',ports=4,per_port=8192,overlap=0.,host_mhz=c.host_mhz,seed=c.seed)).run()
    reference=next(r for r in csv.DictReader(open('results/znand/buffer_expansion/sweep.csv')) if r['buffer_mib']=='8' and r['pattern']=='A2' and r['stripe']=='16384' and r['prefetch']=='True' and r['outstanding']=='2048')
    for k,v in result.items():
        if k=='config':continue
        if k=='counts':
            for key,count in v.items():assert count==float(reference.get('count_'+key) or 0),(key,count,reference.get('count_'+key))
        elif isinstance(v,list):assert v==json.loads(reference[k]),k
        else:assert v==float(reference[k]),(k,v,reference[k])
    result.update(diagnostic='32MiB capacity with independent 512-page reservation limit',matches_8MiB_metrics_exactly=True,
                  runtime_seconds=time.monotonic()-start,source_model_sha256=hashlib.sha256(Path('znand/model.py').read_bytes()).hexdigest())
    (out/'capped_32MiB.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:result[k] for k in ['diagnostic','bandwidth_gbps','buffer_peak_pages','matches_8MiB_metrics_exactly','runtime_seconds']},indent=2))
if __name__=='__main__':main()
