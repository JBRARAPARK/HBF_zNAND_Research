"""Small explicit-spawn checks for macOS-style multiprocessing."""
import argparse
import hashlib
import json
import multiprocessing
import platform
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .model import Config
from .sweep import job, save
from .validate_results import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for case_id, planes in enumerate((8, 16)):
        config = Config(planes=planes, stripe=16384, outstanding=32, prefetch=True)
        cases.append(dict(case_id=case_id, phase='platform_smoke', pattern='A2',
                          per_port=64, overlap=0., config=asdict(config)))
    serial = [job(case) for case in cases]
    context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        parallel = list(pool.map(job, cases))
    if serial != parallel:
        raise RuntimeError('Explicit-spawn results differ from serial simulation')
    save(parallel, out)
    checked = validate(out/'sweep.csv')
    manifest = dict(status='passed', checked_rows=checked, start_method='spawn',
                    matches_serial=True, python=platform.python_version(),
                    platform=platform.system(), machine=platform.machine(),
                    model_sha256=hashlib.sha256(Path(__file__).with_name('model.py').read_bytes()).hexdigest(),
                    note='64 requests per port: portability check, not the 4096-request performance experiment.')
    (out/'cases.json').write_text(json.dumps(cases, indent=2))
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
