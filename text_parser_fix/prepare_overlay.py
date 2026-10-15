"""Create a local ignored two-file overlay from the pinned upstream and patch.

No cloning, dependency installation, network access, model loading or upstream
modification is performed. This only prepares sources for run_checks.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import run_checks as verifier


HERE = Path(__file__).resolve().parent
PATCH_HASH = "d8201a1fe8387755feea2a1601a66ad2a759cff1d4a741ad6057a4a05576b025"
PATCHED_HASHES = verifier.EXPECTED_OVERLAY_SOURCES
RELATIVE_DIRECTORY = Path("src/shopping_grpo/environment")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_overlay(directory):
    for name, expected in PATCHED_HASHES.items():
        path = directory / RELATIVE_DIRECTORY / (name + ".py")
        if path.is_symlink() or not path.is_file() or digest(path) != expected:
            raise RuntimeError(f"Existing overlay does not match the reviewed patch: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path,
                        help="Existing normal Git checkout at the fixed upstream commit")
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    verifier.UPSTREAM = upstream
    if verifier.checkout_commit() != verifier.EXPECTED_COMMIT:
        raise RuntimeError("Upstream checkout is not at the fixed commit")
    for name, expected in verifier.EXPECTED_UPSTREAM_SOURCES.items():
        path = upstream / RELATIVE_DIRECTORY / (name + ".py")
        if not path.is_file() or digest(path) != expected:
            raise RuntimeError(f"Upstream source differs from the reviewed commit: {path}")

    patch = HERE / "product_ids_text_parser.patch"
    if digest(patch) != PATCH_HASH:
        raise RuntimeError("Patch bytes differ from the reviewed patch")
    expected_paths = {str(RELATIVE_DIRECTORY / (name + ".py")) for name in PATCHED_HASHES}
    # Pinning the full patch digest is the main boundary. Also enforce the exact
    # two repository-relative targets; never use --unsafe-paths or a shell.
    actual_paths = set()
    for line in patch.read_text(encoding="utf-8").splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) != 4 or parts[2][2:] != parts[3][2:]:
                raise RuntimeError("Unexpected patch header")
            actual_paths.add(parts[2][2:])
    if actual_paths != expected_paths:
        raise RuntimeError("Patch target set is not exactly the two reviewed source files")
    output = HERE / "overlay"
    if output.is_symlink():
        raise RuntimeError("Refusing a symlink overlay destination")
    if output.exists():
        verify_overlay(output)
        print(json.dumps({"status": "already_prepared", "overlay": str(output)}))
        return
    if shutil.which("git") is None:
        raise RuntimeError("Git is required to apply the reviewed local patch")
    with tempfile.TemporaryDirectory(prefix="prepare-text-parser-", dir="/tmp") as temp:
        staged = Path(temp) / "overlay"
        for name in PATCHED_HASHES:
            relative = RELATIVE_DIRECTORY / (name + ".py")
            destination = staged / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(upstream / relative, destination)
        subprocess.run(["git", "apply", "--check", "--whitespace=error", str(patch)],
                       cwd=staged, check=True)
        subprocess.run(["git", "apply", "--whitespace=error", str(patch)], cwd=staged, check=True)
        verify_overlay(staged)
        # Copy only verified files into a fresh local overlay. No upstream write.
        shutil.copytree(staged, output)
    verify_overlay(output)
    print(json.dumps({"status": "prepared", "overlay": str(output),
                      "upstream_commit": verifier.EXPECTED_COMMIT}))


if __name__ == "__main__":
    main()
