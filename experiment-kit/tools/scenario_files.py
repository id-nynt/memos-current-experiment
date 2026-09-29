"""Materialize inspectable case definitions from the authoritative paired matrix."""
import argparse
import json
from pathlib import Path
import phase8_matrix as matrix


def generate(directory):
    manifest = json.loads(matrix.MANIFEST.read_text())
    matrix.validate(manifest)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for case in manifest['cases']:
        value = dict(matrix_sha256=matrix.sha(manifest), **case)
        path = directory/(case['case_id']+'.json')
        text = json.dumps(value, indent=2)+'\n'
        if path.exists() and path.read_text() != text:
            raise ValueError('Existing scenario differs from matrix: '+str(path))
        path.write_text(text, encoding='utf-8')
    print('100 paired scenario configurations verified:', directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=matrix.ROOT/'scenarios')
    generate(parser.parse_args().directory)
