"""Verify published canonical Git blobs, independent of checkout CRLF conversion.

Default checks HEAD, --index checks staged content before committing. No network,
install or working-tree mutation. Manifest/checksums exclude their own recursion.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def git(*args, data=None):
    return subprocess.check_output(['git', *args], cwd=ROOT, input=data)


def verify(index=False):
    tracked = {}
    args = ('ls-files', '--stage', '-z') if index else ('ls-tree', '-r', '-z', 'HEAD')
    for raw in git(*args).split(b'\0'):
        if not raw:
            continue
        metadata, name = raw.split(b'\t', 1)
        parts = metadata.decode().split()
        if index:
            mode, blob, stage = parts
            if stage != '0':
                raise ValueError('unmerged index')
        else:
            mode, kind, blob = parts
            if kind != 'blob':
                raise ValueError('non-blob publication entry')
        tracked[name.decode('utf-8')] = (mode, blob)
    def read(path):
        return git('cat-file', 'blob', tracked[path][1])
    manifest_bytes = read('PUBLICATION_MANIFEST.json')
    manifest = json.loads(manifest_bytes)
    entries = manifest['files']
    expected_paths = set(tracked) - {'PUBLICATION_MANIFEST.json', 'SHA256SUMS'}
    if len(entries) != len(expected_paths) or {e['path'] for e in entries} != expected_paths:
        raise ValueError('manifest file coverage mismatch')
    output = git('cat-file', '--batch', data=''.join(e['git_blob_sha1'] + '\n' for e in entries).encode())
    stream = io.BytesIO(output)
    hashes = {}
    for entry in entries:
        blob, kind, size = stream.readline().decode().split()
        value = stream.read(int(size))
        if stream.read(1) != b'\n' or kind != 'blob':
            raise ValueError('invalid git blob stream')
        path = entry['path']
        actual = hashlib.sha256(value).hexdigest()
        if (tracked[path] != (entry['mode'], entry['git_blob_sha1']) or blob != entry['git_blob_sha1']
                or len(value) != entry['bytes'] or actual != entry['sha256']):
            raise ValueError('manifest content mismatch: ' + path)
        hashes[path] = actual
    if len(entries) != manifest['total_listed_files'] or sum(e['bytes'] for e in entries) != manifest['total_listed_bytes']:
        raise ValueError('manifest totals mismatch')
    hashes['PUBLICATION_MANIFEST.json'] = hashlib.sha256(manifest_bytes).hexdigest()
    checksum_lines = read('SHA256SUMS').decode().splitlines()
    actual_checksums = {name: sha for sha, name in (line.split('  ', 1) for line in checksum_lines)}
    if len(checksum_lines) != len(hashes) or actual_checksums != hashes:
        raise ValueError('SHA256SUMS mismatch')
    return {'canonical_blobs_verified': len(entries), 'checksum_entries_verified': len(hashes),
            'source': 'index' if index else 'HEAD'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(args.index)))


if __name__ == '__main__':
    main()
