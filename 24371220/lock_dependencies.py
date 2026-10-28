"""Record/check dependencies from the isolated environment used for verification."""
import argparse
import importlib.metadata
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    path = Path(__file__).with_name('requirements.txt')
    if args.write:
        pinned = sorted((f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions()
                         if d.metadata['Name'].lower() not in {'pip', 'setuptools', 'wheel'}), key=str.lower)
        path.write_text('# Locked in isolated WSL Python 3.12; smolagents itself is vendored.\n' +
                        '\n'.join(pinned) + '\n', encoding='utf-8')
    pinned = [line for line in path.read_text(encoding='utf-8').splitlines() if line and not line.startswith('#')]
    for item in pinned:
        name, version = item.split('==')
        if importlib.metadata.version(name) != version:
            raise RuntimeError('Dependency version mismatch: ' + name)
    print(f'Checked {len(pinned)} pinned dependencies')


if __name__ == '__main__':
    main()
