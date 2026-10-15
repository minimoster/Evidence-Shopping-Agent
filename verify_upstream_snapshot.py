"""Verify all included upstream files against the explicit public manifest.

No network, install, training, model call or repository mutation is performed.
README sanitation is declared rather than falsely claiming a byte-exact mirror.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat

ROOT = Path(__file__).resolve().parent


def main():
    manifest = json.loads((ROOT / "UPSTREAM_MANIFEST.json").read_text())
    directory = ROOT / manifest["snapshot_directory"]
    count = 0
    for item in manifest["files"]:
        if not item["included"]:
            continue
        path = directory / item["path"]
        if path.is_symlink() or not path.is_file():
            raise SystemExit("Missing/non-regular snapshot file: " + item["path"])
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item["published_sha256"]:
            raise SystemExit("Published SHA-256 mismatch: " + item["path"])
        if not item["modified"]:
            actual = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
            if actual != item["source_git_blob_sha1"]:
                raise SystemExit("Upstream Git-blob mismatch: " + item["path"])
        count += 1
    print(json.dumps({"source_commit": manifest["source_commit"], "verified_included_files": count,
                      "byte_identical_files": manifest["byte_identical_files"],
                      "declared_sanitized_files": manifest["sanitized_files"],
                      "optional_data_files_not_bundled": manifest["excluded_data_files"],
                      "not_a_full_repository_mirror": True}, indent=2))


if __name__ == "__main__":
    main()
