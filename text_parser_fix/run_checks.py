"""Offline verifier for the two-file source overlay, not a runtime launcher.

Use an existing environment, for example:
python run_checks.py --upstream /path/to/upstream --source overlay --suite all
No repository, model, data archive, compatibility launcher or dependencies are
copied. The unchanged upstream checkout provides the remaining source/tests.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
import unittest


HERE = Path(__file__).resolve().parent
UPSTREAM = HERE.parent / ("upstream_reference" if (HERE.parent / "upstream_reference").is_dir() else "upstream")
EXPECTED_COMMIT = "449bba2686a6ff07327cb3ea77e5f0f91ebb4239"
EXPECTED_UPSTREAM_SOURCES = {
    "actions": "4214855d986422ee54d04cadfbbca11377c85858cbbae44f85697ea51c998e51",
    "projection": "b493b30aeca4a3791d8bf8c893a6769633eec1a66bb5ceaf9b222b3487fd8258",
}
EXPECTED_OVERLAY_SOURCES = {
    "actions": "06f91d3d69961c92588a34bcece3e824c065b85f7e619c40f26a98c75594edd5",
    "projection": "519a534c63ffcda33416f3af4998b6fa07dc1ce42f3e2e61793f8971b2bb2d9c",
}
CONTRACT_MODULES = (
    "test_action_validation", "test_context_window", "test_environment_manifest",
    "test_imports", "test_observation_projection", "test_shop_agent_env",
    "test_shop_tools", "test_smoke_shop_env", "test_structured_observation",
)
BLOCKED = []


def deny_external_actions(event, args):
    if event in {
        "socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto",
        "socket.sendmsg", "subprocess.Popen", "os.system", "os.posix_spawn",
    }:
        BLOCKED.append(event)
        raise RuntimeError(f"Offline parser verifier denied {event}")


def checkout_commit():
    gitdir = UPSTREAM / ".git"
    if not (gitdir / "HEAD").is_file():
        manifest_path = UPSTREAM.parent / "UPSTREAM_MANIFEST.json"
        if not manifest_path.is_file():
            raise RuntimeError("Source needs a pinned Git checkout or explicit bundled manifest")
        manifest = json.loads(manifest_path.read_text())
        if UPSTREAM.name != manifest.get("snapshot_directory"):
            raise RuntimeError("Snapshot directory differs from bundled manifest")
        return manifest["source_commit"]
    head = (gitdir / "HEAD").read_text().strip()
    if not head.startswith("ref: "):
        return head
    ref = head[5:]
    loose = gitdir / ref
    if loose.exists():
        return loose.read_text().strip()
    for line in (gitdir / "packed-refs").read_text().splitlines():
        if line.endswith(" " + ref):
            return line.split()[0]
    raise RuntimeError("Unable to resolve pinned upstream HEAD")


def load_sources(source):
    for name, expected_hash in EXPECTED_UPSTREAM_SOURCES.items():
        path = UPSTREAM / "src/shopping_grpo/environment" / (name + ".py")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError(f"Pinned upstream source has changed: {path}")
    sys.path[:0] = [
        str(UPSTREAM / "src"), str(UPSTREAM), str(UPSTREAM / "tests"),
        str(UPSTREAM / "environments/ShopSimulator/shop_env"), str(HERE / "tests"),
    ]
    import shopping_grpo.environment as environment
    directory = UPSTREAM / "src/shopping_grpo/environment"
    if source == "overlay":
        directory = HERE / "overlay/src/shopping_grpo/environment"
        environment.__path__.insert(0, str(directory))
    sources = {}
    for name in ("actions", "projection"):
        module = importlib.import_module("shopping_grpo.environment." + name)
        path = Path(module.__file__).resolve()
        expected = (directory / (name + ".py")).resolve()
        if path != expected:
            raise RuntimeError(f"Wrong {name} module loaded: {path}; expected {expected}")
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        expected_hashes = (
            EXPECTED_OVERLAY_SOURCES if source == "overlay" else EXPECTED_UPSTREAM_SOURCES
        )
        if source_hash != expected_hashes[name]:
            raise RuntimeError(f"Loaded source differs from the reviewed {source}: {path}")
        sources[name] = {"path": str(path), "sha256": source_hash}
    return sources


def main():
    global UPSTREAM
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("upstream", "overlay"), required=True)
    parser.add_argument("--suite", choices=("contracts", "security", "all"), default="all")
    parser.add_argument("--upstream", type=Path, default=UPSTREAM,
                        help="Existing checkout at the pinned commit; never modified")
    args = parser.parse_args()
    UPSTREAM = args.upstream.resolve()
    sys.dont_write_bytecode = True
    sys.addaudithook(deny_external_actions)
    actual_commit = checkout_commit()
    if actual_commit != EXPECTED_COMMIT:
        raise RuntimeError(f"Wrong upstream commit: {actual_commit}")
    sources = load_sources(args.source)
    results = []
    suites = ("contracts", "security") if args.suite == "all" else (args.suite,)
    for suite_name in suites:
        loader = unittest.TestLoader()
        modules = CONTRACT_MODULES if suite_name == "contracts" else ("test_text_product_parsing",)
        suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in modules)
        started = time.monotonic()
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        # A subtest emits its own failure event. Count affected test methods
        # separately so a fuzz matrix cannot produce a negative passed count.
        def parent_test_id(test):
            return getattr(test, "test_case", test).id()

        failed_tests = {parent_test_id(test) for test, _ in result.failures}
        errored_tests = {parent_test_id(test) for test, _ in result.errors}
        skipped_tests = {parent_test_id(test) for test, _ in result.skipped}
        results.append({
            "suite": suite_name, "tests_run": result.testsRun,
            "passed": result.testsRun - len(failed_tests | errored_tests | skipped_tests),
            "failures": len(failed_tests), "errors": len(errored_tests),
            "skipped": len(skipped_tests), "failure_events": len(result.failures),
            "error_events": len(result.errors), "successful": result.wasSuccessful(),
            "elapsed_seconds": round(time.monotonic() - started, 4),
        })
    summary = {
        "source": args.source, "upstream_commit": actual_commit, "loaded_sources": sources,
        "external_network_and_processes": "denied", "blocked_action_attempts": BLOCKED,
        "token_counter": "len: character-count proxy, not a model tokenizer",
        "suites": results, "successful": all(result["successful"] for result in results),
    }
    output = HERE / "results" / f"{args.source}_{args.suite}_summary.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["successful"] and not BLOCKED else 1


if __name__ == "__main__":
    raise SystemExit(main())
