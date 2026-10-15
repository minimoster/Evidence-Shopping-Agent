"""Resolve the bundled pinned source snapshot without requiring a second clone."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
UPSTREAM_COMMIT = "449bba2686a6ff07327cb3ea77e5f0f91ebb4239"


def upstream_path() -> Path:
    explicit = os.environ.get("EVIDENCE_SHOPPING_UPSTREAM")
    if explicit:
        return Path(explicit).expanduser().resolve()
    snapshot = ROOT / "upstream_reference"
    return snapshot if snapshot.is_dir() else ROOT / "upstream"
