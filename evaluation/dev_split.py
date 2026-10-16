"""Prepare a reproducible, IDs-only development split without reading Final-200.

Only pinned upstream GRPO train/validation ID lists are accepted. This module
never loads environment goals, queries, labels, models, or evaluation results.
The separate, explicitly supplied blind-ID manifest is mandatory. Final IDs in
the candidate pool are an error, not something silently filtered away.

Example (local files only; the optional dataset is not bundled with this code)::

    python -m evaluation.dev_split \
      --source /local/upstream/data/grpo/validation.jsonl \
      --source-relative-path data/grpo/validation.jsonl \
      --final-id-manifest upstream_reference/src/shopping_grpo/resources/blind_final_task_ids.json

The default output is runtime/dev20, an ignored local directory. A development
split is not an unbiased held-out test and must never be reported as Final-200.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_TASK_COUNT = 20
DEFAULT_SEED = 20261016
SCHEMA_VERSION = "shopping-development-split-v1"
BLIND_IDS_SCHEMA = "shopping-blind-task-ids-v1"
BLIND_IDS_KEY = "src/shopping_grpo/resources/blind_final_task_ids.json"
PERMITTED_SOURCE_KEYS = (
    "data/grpo/validation.jsonl",
    "data/grpo/train.jsonl",
)


class SplitError(ValueError):
    """Invalid, unavailable, or unverified development-split input."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _read_bytes(path: Path, description: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SplitError(f"{description} unavailable: {path}") from exc


def _json_object(data: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SplitError(f"{description} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SplitError(f"{description} must be a JSON object")
    return value


def _manifest_entry(manifest: dict[str, Any], key: str) -> dict[str, Any]:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise SplitError("provenance manifest must contain a files list")
    matches = [item for item in files if isinstance(item, dict) and item.get("path") == key]
    if len(matches) != 1:
        raise SplitError(f"provenance manifest must pin exactly one entry for {key}")
    return matches[0]


def _verify_pinned_bytes(data: bytes, entry: dict[str, Any], description: str) -> None:
    size = entry.get("source_bytes")
    digest = entry.get("source_git_blob_sha1")
    if type(size) is not int or size < 0 or len(data) != size:
        raise SplitError(f"{description} does not match pinned source byte count")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{40}", digest):
        raise SplitError(f"{description} has no valid pinned source Git blob SHA1")
    if _git_blob_sha1(data) != digest:
        raise SplitError(f"{description} does not match pinned source Git blob SHA1")
    # Included, unmodified files additionally have a pinned publication SHA256.
    if entry.get("published_sha256") is not None and entry.get("modified") is False:
        if _sha256(data) != entry["published_sha256"]:
            raise SplitError(f"{description} does not match pinned published SHA256")


def _valid_task_id(value: Any) -> bool:
    return type(value) is int and value >= 0


def _load_final_ids(data: bytes) -> set[int]:
    document = _json_object(data, "Final-200 IDs manifest")
    if set(document) != {"schema_version", "task_ids"}:
        raise SplitError("Final-200 manifest must contain IDs only and its schema_version")
    if document.get("schema_version") != BLIND_IDS_SCHEMA:
        raise SplitError("unsupported Final-200 IDs manifest schema")
    ids = document.get("task_ids")
    if not isinstance(ids, list) or not all(_valid_task_id(value) for value in ids):
        raise SplitError("Final-200 task IDs must be nonnegative JSON integers")
    if len(ids) != 200 or len(set(ids)) != 200:
        raise SplitError("Final-200 IDs manifest must contain exactly 200 unique IDs")
    return set(ids)


def _load_candidate_ids(data: bytes) -> list[int]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SplitError("development source must be UTF-8 JSONL") from exc
    ids: list[int] = []
    seen: set[int] = set()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            # Never echo source lines: they could contain unexpected private data.
            raise SplitError(f"development source line {number} is invalid JSON") from exc
        if not isinstance(row, dict) or set(row) != {"task_id"}:
            raise SplitError(f"development source line {number} must contain only task_id")
        task_id = row["task_id"]
        if not _valid_task_id(task_id):
            raise SplitError(f"development source line {number} has an invalid task_id")
        if task_id in seen:
            raise SplitError(f"development source has a duplicate task_id at line {number}")
        seen.add(task_id)
        ids.append(task_id)
    return ids


def task_ids_jsonl(task_ids: list[int]) -> bytes:
    """Canonical ID-only bytes, compatible with the upstream task loader."""
    return "".join(json.dumps({"task_id": value}, separators=(",", ":")) + "\n" for value in task_ids).encode("utf-8")


def select_development_split(
    source_path: str | Path,
    final_id_manifest_path: str | Path,
    *,
    source_relative_path: str,
    provenance_manifest_path: str | Path = ROOT / "UPSTREAM_MANIFEST.json",
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Validate local provenance and return metadata for exactly 20 IDs.

    Selection is SHA256 ranking over ``schema NUL seed NUL task_id``. The
    selected set is independent of source row order and Python PRNG versions;
    task execution order is ascending numeric ID. Output contains no gold data.
    """
    if type(seed) is not int:
        raise SplitError("seed must be an integer")
    if source_relative_path not in PERMITTED_SOURCE_KEYS:
        raise SplitError("source must be an explicitly pinned non-final GRPO split")
    source = Path(source_path).resolve()
    # Resolve symlinks first and reject Final-200 paths before opening them.
    if source.parts[-3:] != tuple(Path(source_relative_path).parts):
        raise SplitError("source path must end with its permitted non-final manifest path")
    if final_id_manifest_path is None:
        raise SplitError("an explicit Final-200 IDs exclusion manifest is required")
    final_manifest = Path(final_id_manifest_path).resolve()
    if final_manifest.name != Path(BLIND_IDS_KEY).name:
        raise SplitError("supply the separate blind_final_task_ids.json IDs-only manifest")
    if source == final_manifest:
        raise SplitError("source and Final-200 IDs manifest must be different files")

    provenance_bytes = _read_bytes(Path(provenance_manifest_path), "provenance manifest")
    provenance = _json_object(provenance_bytes, "provenance manifest")
    commit = provenance.get("source_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SplitError("provenance manifest requires a pinned 40-character source commit")
    source_entry = _manifest_entry(provenance, source_relative_path)
    final_entry = _manifest_entry(provenance, BLIND_IDS_KEY)

    # Validate the separate exclusion list before opening any candidate source.
    final_bytes = _read_bytes(final_manifest, "Final-200 IDs manifest")
    _verify_pinned_bytes(final_bytes, final_entry, "Final-200 IDs manifest")
    final_ids = _load_final_ids(final_bytes)
    source_bytes = _read_bytes(source, "permitted development source")
    _verify_pinned_bytes(source_bytes, source_entry, "development source")
    candidates = _load_candidate_ids(source_bytes)
    overlap = set(candidates) & final_ids
    if overlap:
        raise SplitError(f"development source contains {len(overlap)} excluded Final-200 ID(s)")
    if len(candidates) < DEVELOPMENT_TASK_COUNT:
        raise SplitError(f"insufficient development pool: {len(candidates)} unique IDs; require 20")

    def rank(task_id: int) -> tuple[str, int]:
        payload = f"{SCHEMA_VERSION}\0{seed}\0{task_id}".encode("ascii")
        return _sha256(payload), task_id

    selected = sorted(sorted(candidates, key=rank)[:DEVELOPMENT_TASK_COUNT])
    output_bytes = task_ids_jsonl(selected)
    return {
        "schema_version": SCHEMA_VERSION,
        "split_role": "development_only",
        "evaluated": False,
        "selection": {
            "algorithm": "sha256_rank_v1",
            "rank_input": "shopping-development-split-v1\\0{seed}\\0{task_id}",
            "output_order": "ascending_task_id",
            "seed": seed,
            "task_count": DEVELOPMENT_TASK_COUNT,
        },
        "source": {
            "repository": provenance.get("repository"),
            "commit": commit,
            "path": source_relative_path,
            "sha256": _sha256(source_bytes),
            "git_blob_sha1": _git_blob_sha1(source_bytes),
            "bytes": len(source_bytes),
            "task_count": len(candidates),
            "provenance_manifest_sha256": _sha256(provenance_bytes),
        },
        "final_exclusion": {
            "path": BLIND_IDS_KEY,
            "sha256": _sha256(final_bytes),
            "git_blob_sha1": _git_blob_sha1(final_bytes),
            "task_count": len(final_ids),
            "source_overlap_count": 0,
            "selected_overlap_count": 0,
        },
        "task_ids": selected,
        "tasks_jsonl_sha256": _sha256(output_bytes),
        "contains_queries_or_labels": False,
    }


def write_split(manifest: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    """Write a new output directory; never overwrite an existing development split."""
    directory = Path(output_dir)
    if directory.exists():
        raise SplitError(f"output directory already exists; refusing to overwrite: {directory}")
    tasks = task_ids_jsonl(manifest["task_ids"])
    if _sha256(tasks) != manifest.get("tasks_jsonl_sha256"):
        raise SplitError("manifest task IDs do not match their recorded output SHA256")
    metadata = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    directory.mkdir(parents=True, exist_ok=False)
    tasks_path = directory / "tasks.jsonl"
    manifest_path = directory / "manifest.json"
    try:
        with tasks_path.open("xb") as stream:
            stream.write(tasks)
        with manifest_path.open("xb") as stream:
            stream.write(metadata)
    except OSError:
        # Remove only this invocation's incomplete files, never preexisting data.
        tasks_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        directory.rmdir()
        raise
    return tasks_path, manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path, help="Existing, permitted local GRPO ID-only JSONL")
    parser.add_argument("--source-relative-path", required=True, choices=PERMITTED_SOURCE_KEYS)
    parser.add_argument("--final-id-manifest", required=True, type=Path, help="Explicit IDs-only Final-200 exclusion list")
    parser.add_argument("--provenance-manifest", type=Path, default=ROOT / "UPSTREAM_MANIFEST.json")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runtime" / "dev20")
    args = parser.parse_args(argv)
    try:
        manifest = select_development_split(
            args.source,
            args.final_id_manifest,
            source_relative_path=args.source_relative_path,
            provenance_manifest_path=args.provenance_manifest,
            seed=args.seed,
        )
        tasks_path, manifest_path = write_split(manifest, args.output_dir)
    except (SplitError, OSError) as exc:
        parser.exit(2, f"Development split not created: {exc}\n")
    print(json.dumps({"status": "prepared_not_evaluated", "tasks": str(tasks_path), "manifest": str(manifest_path), "task_count": 20, "seed": args.seed}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
