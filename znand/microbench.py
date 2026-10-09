"""Controlled physical transitions and partial Read sizes, with analytic checks."""
from dataclasses import replace
from pathlib import Path
import csv,json
from .model import Config,Simulator,Input,PAGE

def main():
    out=Path('results/znand/microbench');out.mkdir(parents=True,exist_ok=True)
    c=Config(ports=1,availability=1.,trace=True)
    rows=[]
    pairs=[('page_buffer_reuse',0,0,'page_buffer',0.),('even_odd',0,1,'short',2.),('ssl_next',1,2,'mid',2.08),
           ('block_next',11,12,'mid',2.08),('wl_wrap',23,24,'mid',2.08),('same_block_wl',0,24,'long',12.16),
           ('nonsequential',0,7,'long',12.16),('group_switch',10103,10104,'group',20.69)]
    for name,q0,q1,kind,tr in pairs:
        rs=[Input(0,q0*128*4096,64,30),Input(0,q1*128*4096+(64 if q0==q1 else 0),64,100)]
        sim=Simulator(c,rs);r=sim.run();second=sim.req[1]
        expected=c.lookup_us+c.ca_us+tr+PAGE/(c.io_gbps*1000)+c.turnaround_us+c.ecc_us+.001
        measured=second['end']-second['accepted']
        assert abs(expected-measured)<1e-8,(name,expected,measured)
        rows.append(dict(case=name,kind=kind,second_tr_us=tr,expected_latency_us=expected,measured_latency_us=measured,
                         sensing_reads=r['counts'].get('sensing_reads',0),page_buffer_hits=r['counts'].get('page_buffer_hits',0)))
        (out/(name+'.json')).write_text(json.dumps(sim.log,indent=2))
    with (out/'transitions.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,list(rows[0]));w.writeheader();w.writerows(rows)
    print('validated',len(rows),'physical transition cases')
if __name__=='__main__':main()
