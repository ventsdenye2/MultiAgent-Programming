"""Verify the complete pinned runtime package without importing dependencies."""
import hashlib
import json
from pathlib import Path


def verify(base=None):
    root = (Path(base) if base else Path(__file__).parent) / 'vendor/smolagents'
    manifest = json.loads((root / 'UPSTREAM.json').read_text(encoding='utf-8'))
    assert manifest['commit'] == '12c1bc820eca50ace6f80a21d90426d41d74f845'
    assert manifest['version'] == '1.26.0'
    for item in manifest['files']:
        data = (root / item['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item['sha256'], item['path']
        assert hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest() == item['git_blob'], item['path']
    expected = {item['path'] for item in manifest['files']}
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and p.suffix != '.pyc' and p.name != 'UPSTREAM.json'}
    assert actual == expected, {'missing': expected - actual, 'extra': actual - expected}
    return {'version': manifest['version'], 'commit': manifest['commit'], 'verified_files': len(expected)}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
