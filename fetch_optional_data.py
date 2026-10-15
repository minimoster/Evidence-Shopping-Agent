"""Explicit opt-in retrieval of omitted data from the pinned public upstream.

No arguments: list only, no network. The caller must independently establish
permission. This tool does not assert that redistribution is authorized.
Never installs software, downloads weights, invokes APIs/models, or trains.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent


def validate_bytes(content: bytes, item: dict) -> str:
    if len(content) != item["source_bytes"]:
        raise ValueError("Data byte count differs from fixed upstream manifest")
    actual = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    if actual != item["source_git_blob_sha1"]:
        raise ValueError("Data Git-blob SHA-1 differs from fixed upstream manifest")
    return hashlib.sha256(content).hexdigest()


def main():
    manifest = json.loads((ROOT / "UPSTREAM_MANIFEST.json").read_text())
    candidates = {item["path"]: item for item in manifest["files"] if not item["included"]}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--select", action="append", default=[], choices=sorted(candidates))
    parser.add_argument("--all-data", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--acknowledge-third-party-data", action="store_true")
    args = parser.parse_args()
    selected = sorted(candidates) if args.all_data else list(dict.fromkeys(args.select))
    if not selected:
        print(json.dumps({"action": "list_only_no_network", "source_commit": manifest["source_commit"],
                          "files": [{"path": path, "bytes": item["source_bytes"],
                                     "git_blob_sha1": item["source_git_blob_sha1"],
                                     "permission_status": item["permission_status"]}
                                    for path, item in candidates.items()]}, indent=2))
        return
    if not args.allow_network or not args.acknowledge_third_party_data:
        parser.error("Retrieval requires --allow-network and --acknowledge-third-party-data after you establish permission")
    receipts = []
    source_root = (ROOT / manifest["snapshot_directory"]).resolve()
    for relative in selected:
        item = candidates[relative]
        destination = source_root / relative
        if source_root not in destination.resolve().parents or destination.is_symlink():
            raise ValueError("Unsafe data destination")
        if destination.exists():
            checksum = validate_bytes(destination.read_bytes(), item)
            receipts.append({"path": relative, "status": "already_matches", "sha256": checksum})
            continue
        url = ("https://raw.githubusercontent.com/" + manifest["repository"] + "/"
               + manifest["source_commit"] + "/" + quote(relative, safe="/"))
        with urlopen(url, timeout=60) as response:
            if urlsplit(response.url).hostname != "raw.githubusercontent.com":
                raise ValueError("Unexpected data download destination")
            content = response.read(item["source_bytes"] + 1)
        checksum = validate_bytes(content, item)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        receipts.append({"path": relative, "status": "downloaded_and_verified", "sha256": checksum})
    output = ROOT / "runtime"
    output.mkdir(exist_ok=True)
    (output / "data_fetch_receipts.json").write_text(json.dumps(receipts, indent=2) + "\n")
    print(json.dumps(receipts, indent=2))


if __name__ == "__main__":
    main()
