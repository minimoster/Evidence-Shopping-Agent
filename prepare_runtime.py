"""Unpack and verify frozen data, then build a local full-corpus search index.

Run only after cloning and reviewing the pinned upstream source. Uses the
standard library and the reviewed upstream SQLite builder, no installer.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

from offline_checks import deny_external_actions

ROOT = Path(__file__).resolve().parent
from project_paths import upstream_path
UPSTREAM = upstream_path()
SHOP = UPSTREAM / "environments/ShopSimulator/shop_env"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products-archive", type=Path, default=SHOP / "data/fine_items_eval_train_all.json.gz")
    args = parser.parse_args()
    if not args.products_archive.is_file():
        parser.error("Product archive is intentionally not bundled. See DATASETS.md; explicitly fetch or supply an authorized local archive.")
    sys.addaudithook(deny_external_actions)
    runtime = ROOT / "runtime"
    runtime.mkdir(exist_ok=True)
    destination = runtime / "items_eval_train.json"
    digest = hashlib.sha256()
    with gzip.open(args.products_archive, "rb") as source:
        with destination.open("wb") as output:
            while block := source.read(1024 * 1024):
                output.write(block)
                digest.update(block)
    actual = digest.hexdigest()
    expected = json.loads((UPSTREAM / "data/environment.json").read_text())["product_data_sha256"]
    if actual != expected:
        raise ValueError(f"Product SHA-256 mismatch: {actual}")
    sys.path[:0] = [str(SHOP), str(SHOP / "scripts")]
    from build_index import iter_json_array
    from web_agent_site.engine.search import build_index
    manifest = build_index(iter_json_array(destination), runtime / "products.sqlite3",
                           product_data_sha256=actual)
    (runtime / "products.manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
