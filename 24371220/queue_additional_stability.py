"""Wait for the registered course cohort, then run the authorized extra cohort."""
import argparse
import fcntl
from pathlib import Path
import subprocess
import sys
import time

from run_stability import read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True, type=Path)
    parser.add_argument('--run-paid', action='store_true')
    args = parser.parse_args()
    if not args.run_paid:
        parser.error('--run-paid is required')
    root = Path(__file__).resolve().parent
    study = args.study.resolve()
    lock = (root / 'experiments/smolagents/.evaluation.lock').open('a+')
    print('Waiting for course evaluation lock', flush=True)
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(15)
    expected = [study / 'samples' / f'{task}-{n:02d}' / 'sample.json'
                for n in range(1, 11) for task in ('source', 'paper')]
    rows = [read(path, {}) for path in expected]
    if any(row.get('status') not in {'passed', 'failed'} for row in rows):
        raise SystemExit('Course cohort incomplete or infrastructure failure; no extra requests started')
    fcntl.flock(lock, fcntl.LOCK_UN)
    lock.close()
    print('Course cohort complete; starting extra tasks', flush=True)
    return subprocess.call([sys.executable, str(root / 'run_stability.py'),
                            '--run-paid', '--phase', 'additional', '--study', str(study)], cwd=root)


if __name__ == '__main__':
    raise SystemExit(main())
