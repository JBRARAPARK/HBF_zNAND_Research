"""Functional smoke for the current DIE layout; not a peak-throughput benchmark."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from znand.model import Config, Simulator
from znand.workloads import workload


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        parser.error('Choose an empty output directory to preserve previous results')
    args.out.mkdir(parents=True,exist_ok=True)
    cfg=Config.die32()
    cases=[]
    for pattern in ('A1','A2','B','C1','C2','C3'):
        # B's 64B sequence needs enough requests to visit all eight channels.
        per_port=1024 if pattern=='B' else 128
        sim=Simulator(cfg,workload(pattern,per_port=per_port))
        result=sim.run()
        assert sim.finished==4*per_port and len(sim.plane)==32
        assert len(sim.channel_data)==8 and all(sim.channel_data)
        assert sim.used_peak<=cfg.buffer_pages
        assert result['bandwidth_gbps']<=256.
        for port in range(4):
            ends=[r['end'] for r in sim.req if r['port']==port]
            assert ends==sorted(ends)
        result.update(pattern=pattern,per_port=per_port,
                      scope='Functional finite-trace smoke, includes fill/drain; not a maximum-throughput measurement')
        (args.out/f'{pattern}.json').write_text(json.dumps(result,indent=2)+'\n')
        cases.append(dict(pattern=pattern,completed=sim.finished,channels_used=8,planes=32,status='passed'))
    sources=['znand/model.py','znand/run.py','znand/host_ceiling.py','znand/stream64.py',
             'scripts/die_layout_smoke.py','test_znand_die_layout.py','configs/die4_channel2_plane4.json']
    manifest=dict(status='passed',cases=cases,
                  topology=cfg.topology(),
                  confirmed='4 DIE, 2 independent CA/Data channels per DIE, 4 planes per channel',
                  source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources})
    (args.out/'validation.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Passed 6 functional cases, 8 independent channels, 32 planes')


if __name__=='__main__':main()
