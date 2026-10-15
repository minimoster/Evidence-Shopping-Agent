"""Run selected upstream CPU checks with outbound connects/processes denied.

This is not a model evaluation or an agent rollout. Upstream test fixtures may
contain hidden reward labels for testing the evaluator; no labels reach the
new policy/prototype. No training or model-loading code is invoked here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "upstream"
SHOP = UPSTREAM / "environments/ShopSimulator/shop_env"


DENIED_EVENTS = []


def deny_external_actions(event, args):
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto",
                 "socket.sendmsg", "subprocess.Popen", "os.system", "os.posix_spawn"}:
        DENIED_EVENTS.append(event)
        raise RuntimeError(f"Offline smoke denied {event}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=["simulator", "contracts", "cpu"])
    args = parser.parse_args()
    sys.addaudithook(deny_external_actions)
    sys.path[:0] = [str(UPSTREAM / "src"), str(UPSTREAM), str(SHOP)]
    started = time.monotonic()
    if args.suite == "cpu":
        from shopping_grpo.smoke import run_cpu_smoke
        result = run_cpu_smoke()
        summary = {"suite": "upstream_cpu_synthetic_contracts", **result,
                   "check_count": len(result["checks"]), "external_network": "denied"}
    else:
        loader = unittest.TestLoader()
        if args.suite == "simulator":
            suite = loader.discover(str(SHOP / "tests"), pattern="test_*.py")
        else:
            # Reviewed, offline-only subset. Excludes wheel install, training,
            # API-backed model rollout, collection, and evaluation datasets.
            names = ["test_action_validation", "test_context_window",
                     "test_environment_manifest", "test_imports",
                     "test_observation_projection", "test_shop_agent_env",
                     "test_shop_tools", "test_smoke_shop_env",
                     "test_structured_observation"]
            sys.path.insert(0, str(UPSTREAM / "tests"))
            suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in names)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        summary = {"suite": args.suite, "tests_run": result.testsRun,
                   "failures": len(result.failures), "errors": len(result.errors),
                   "skipped": len(result.skipped), "passed": result.testsRun
                   - len(result.failures) - len(result.errors) - len(result.skipped),
                   "successful": result.wasSuccessful(), "external_network": "denied"}
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    summary["blocked_external_action_attempts"] = list(DENIED_EVENTS)
    output = ROOT / "results" / f"{args.suite}_summary.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if summary.get("successful") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
