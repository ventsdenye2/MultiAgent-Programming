"""Run offline regressions with native Linux temporary files and save results."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile


def main():
    if sys.platform != 'linux':
        raise SystemExit('Run this test launcher in WSL')
    root = Path(__file__).resolve().parent
    stamp = datetime.datetime.now().strftime('offline-%Y%m%d-%H%M%S')
    out = root / 'experiments/smolagents' / stamp
    out.mkdir(parents=True)
    native = Path(tempfile.mkdtemp(prefix='smolagents-offline-'))
    fs = subprocess.check_output(['stat', '-f', '-c', '%T', str(native)], text=True).strip()
    if fs not in {'ext2/ext3', 'tmpfs', 'btrfs', 'xfs'}:
        raise RuntimeError('Tests require native Linux temp files')
    env = os.environ.copy()
    env.update(TMPDIR=str(native), PYTHONDONTWRITEBYTECODE='1')
    cmd = [sys.executable, '-m', 'pytest', '-q', 'test_smolagents.py', 'test_smolagents_materials.py',
           '--basetemp', str(native / 'pytest'), '--junitxml', str(out / 'junit.xml')]
    with (out / 'pytest.log').open('w', encoding='utf-8') as log:
        rc = subprocess.call(cmd, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    for path in (native / 'pytest').rglob('*'):
        if path.is_file() and not path.is_symlink() and path.name in {
            'run.log', 'run-result.json', 'patch.diff', 'capacity.json'}:
            target = out / 'test-artifacts' / path.relative_to(native / 'pytest')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    (out / 'summary.json').write_text(json.dumps({'exit_code': rc, 'native': str(native),
        'filesystem': fs, 'python': sys.version, 'provider_calls': 0, 'command': cmd}, indent=2))
    print((out / 'pytest.log').read_text())
    print('Offline artifacts: ' + str(out))
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
