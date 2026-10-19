"""Run local HTTP/UI contracts; permit loopback only, deny external operations.

Separate from evaluation.semantic_checks, whose no-socket policy is unchanged.
These are HTTP integration tests, not browser rendering or real-model evaluation.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

from project_paths import ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    temp = ROOT / 'results' / 'product-test-temp'
    temp.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(temp)
    denied = []
    def guard(event, values):
        reject = event in {'subprocess.Popen', 'os.system', 'os.posix_spawn', 'socket.sendto', 'socket.sendmsg'}
        if event in {'socket.connect', 'socket.bind'}:
            reject = not isinstance(values[1], tuple) or values[1][0] != '127.0.0.1'
        if event == 'socket.getaddrinfo':
            reject = values[0] != '127.0.0.1'
        if reject:
            denied.append(event)
            raise RuntimeError('external operation blocked')
    sys.addaudithook(guard)
    modules = ['tests_demo.test_core', 'tests_demo.test_web', 'tests_demo.test_confirmed_web']
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(x) for x in modules)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    summary = {'suite': 'offline_product_and_loopback_http', 'modules': modules,
        'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'skipped': len(result.skipped), 'successful': result.wasSuccessful(),
        'network_policy': '127.0.0.1_only', 'blocked_external_attempts': denied,
        'browser_rendering_tested': False, 'real_model_calls': 0, 'real_simulator_tasks': 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(summary, stream, indent=2); stream.write('\n')
    print(json.dumps(summary))
    return 0 if result.wasSuccessful() and not denied else 1


if __name__ == '__main__':
    raise SystemExit(main())
