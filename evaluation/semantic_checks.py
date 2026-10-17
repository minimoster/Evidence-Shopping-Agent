"""Run the small semantic/guard regression set with external actions denied."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

MODULES = (
    "prototype.tests.test_requirements", "prototype.tests.test_purchase_guard",
    "prototype.tests.test_public_schema", "tests_evaluation.test_constraints",
    "tests_evaluation.test_natural_constraints", "tests_evaluation.test_query_analysis_runner",
    "tests_evaluation.test_runner", "tests_evaluation.test_semantic_constraints",
    "tests_evaluation.test_semantic_readiness",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    from offline_checks import DENIED_EVENTS, deny_external_actions
    from project_paths import ROOT
    # Windows managed sandboxes may expose an unwritable default temp path.
    # Keep test-owned temporary artifacts within this project's ignored results.
    test_temp = ROOT / "results" / "semantic-test-temp"
    test_temp.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(test_temp)
    sys.addaudithook(deny_external_actions)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in MODULES)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    summary = {"suite": "bounded_semantics_and_guard_regression", "modules": list(MODULES),
               "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "skipped": len(result.skipped), "successful": result.wasSuccessful(),
               "external_actions": "denied", "blocked_external_action_attempts": list(DENIED_EVENTS),
               "evidence_kind": "synthetic_unit_and_mocked_integration_tests",
               "real_development_queries_tested": 0, "model_calls": 0, "simulator_steps": 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    print(json.dumps(summary))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
