"""Real loopback HTTP end-to-end tests; model/store are explicitly offline fixtures."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest

from tests_demo import test_web
from shopping_demo.web import DemoServer
from shopping_demo.confirmed import QUERY, APPROXIMATE_QUERY, MISSING_BUDGET_QUERY, UNSUPPORTED_QUERY
from evaluation.replay import verify_gate_replay
from evaluation.constraints import compile_query
from prototype import EvidenceLedger, verify_purchase


class ConfirmedWebTests(unittest.TestCase):
    request = test_web.LocalWebTest.request
    session = test_web.LocalWebTest.session

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = DemoServer(('127.0.0.1', 0), product_output_root=Path(cls.temp.name) / 'runs')
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host, cls.origin = cls.server.allowed_host, cls.server.allowed_origin

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def start(self, query=QUERY, scenario='recovery'):
        data, cookie = self.session()
        options = {'cookie': cookie, 'csrf': data['csrf']}
        code, state, _ = self.request('POST', '/api/confirmed/new', body={'query': query, 'scenario': scenario}, **options)
        self.assertEqual(code, 200)
        return state, options

    def confirm(self, state, options):
        code, result, _ = self.request('POST', '/api/confirmed/confirm', body={
            'revision': state['revision'], 'review_sha256': state['review']['review_sha256'], 'accepted': True}, **options)
        self.assertEqual(code, 200)
        return result

    def run_and_trace(self, state, options):
        code, result, _ = self.request('POST', '/api/confirmed/run', body={'revision': state['revision']}, **options)
        self.assertEqual(code, 200)
        self.assertEqual(result['status'], 'finished')
        code, trace, _ = self.request('GET', '/api/confirmed/trace?revision=' + state['revision'], cookie=options['cookie'])
        self.assertEqual(code, 200)
        return result, trace

    def test_http_input_explicit_confirmation_recovery_and_readonly_replay(self):
        state, options = self.start()
        self.assertEqual(state['status'], 'awaiting_confirmation')
        self.assertEqual(self.request('POST', '/api/confirmed/run', body={'revision': state['revision']}, **options)[0], 400)
        self.assertEqual(self.request('POST', '/api/confirmed/confirm', body={
            'revision': state['revision'], 'review_sha256': state['review']['review_sha256'], 'accepted': False}, **options)[0], 400)
        state = self.confirm(state, options)
        result, trace = self.run_and_trace(state, options)
        c = trace['rows'][2]
        self.assertTrue(result['c_outcome']['purchased'])
        self.assertEqual([e['executed'] for e in c['gate_events']], [False, True])
        self.assertIn('Evidence gate rejected', json.dumps(c['usage'], ensure_ascii=False))
        self.assertEqual([r['model_calls'] for r in trace['rows']], [2, 2, 4])
        self.assertEqual(result['summary']['physical_requests'], 6)
        code, replay, _ = self.request('POST', '/api/confirmed/replay', body={'revision': state['revision']}, **options)
        self.assertEqual((code, replay['gate_decisions_checked']), (200, 2))
        _, after, _ = self.request('GET', '/api/confirmed', cookie=options['cookie'])
        self.assertEqual(after['summary'], result['summary'])
        self.assertEqual(self.request('POST', '/api/confirmed/run', body={'revision': state['revision']}, **options)[0], 400)

    def test_http_approximate_and_missing_budget_require_new_human_source(self):
        for query in [APPROXIMATE_QUERY, MISSING_BUDGET_QUERY]:
            state, options = self.start(query)
            self.assertEqual(state['status'], 'needs_clarification')
            old = state
            code, state, _ = self.request('POST', '/api/confirmed/clarify', body={'revision': state['revision'], 'ceiling_cny': '100'}, **options)
            self.assertEqual((code, state['status']), (200, 'awaiting_confirmation'))
            self.assertNotEqual(state['revision'], old['revision'])
            self.assertEqual(state['review']['original_query'], query)
            self.assertEqual(state['review']['proposal'], old['review']['proposal'])
            self.assertEqual(state['review']['budget_clarification']['source_review'], old['review'])
            self.assertEqual(state['review']['proposal_usage'], old['review']['proposal_usage'])
            self.assertEqual(self.request('POST', '/api/confirmed/confirm', body={
                'revision': old['revision'], 'review_sha256': old['review']['review_sha256'], 'accepted': True}, **options)[0], 400)
            result, trace = self.run_and_trace(self.confirm(state, options), options)
            self.assertTrue(result['c_outcome']['purchased'])
            self.assertEqual(trace['plan']['confirmation']['review']['original_query'], query)

    def test_http_unknown_function_and_free_text_cannot_be_repaired_by_budget(self):
        for query in [UNSUPPORTED_QUERY, '请给我一个全新的任意自然语言商品建议']:
            state, options = self.start(query)
            if query != UNSUPPORTED_QUERY:
                code, state, _ = self.request('POST', '/api/confirmed/clarify', body={'revision': state['revision'], 'ceiling_cny': '100'}, **options)
                self.assertEqual(code, 200)
            self.assertEqual(state['status'], 'needs_clarification')
            self.assertEqual(self.request('POST', '/api/confirmed/confirm', body={
                'revision': state['revision'], 'review_sha256': state['review']['review_sha256'], 'accepted': True}, **options)[0], 400)

    def test_http_selected_variant_price_invalidates_old_evidence_and_stops(self):
        for scenario in ['variant_price', 'variant_unknown']:
            state, options = self.start(scenario=scenario)
            result, trace = self.run_and_trace(self.confirm(state, options), options)
            c = trace['rows'][2]
            self.assertFalse(result['c_outcome']['purchased'])
            self.assertEqual([e['executed'] for e in c['gate_events']], [False, False])
            expected_reason = 'over_budget' if scenario == 'variant_price' else 'price_unknown'
            self.assertIn(expected_reason, c['gate_events'][1]['decision']['reasons'])
            self.assertEqual(c['gate_events'][1]['observation_state']['product']['price'], '79')
            self.assertEqual(c['gate_events'][1]['observation_state']['selected_price'], '129' if scenario == 'variant_price' else None)
            self.assertGreater(c['gate_events'][1]['decision']['revision'], c['gate_events'][0]['decision']['revision'])
            self.assertEqual(c['trajectory']['steps'][-1]['tool_name'], 'finish_without_purchase')
            self.assertEqual(verify_gate_replay(c)['gate_decisions_checked'], 2)
            # A prior valid decision also becomes unusable after a public revision.
            state_before = c['gate_events'][0]['observation_state']
            requirements = compile_query('category:耳机;color:白色;预算:不超过100元').requirements
            ledger = EvidenceLedger(); ledger.ingest(state_before)
            old_decision = verify_purchase(requirements, ledger, intended_asin='000000000101', intended_options={'颜色': '白色'})
            self.assertTrue(old_decision.allowed)
            ledger.ingest(c['gate_events'][1]['observation_state'])
            self.assertFalse(ledger.decision_is_current(old_decision, requirements))

    def test_new_intake_invalidates_confirmed_revision_and_cannot_cross_sessions(self):
        state, options = self.start()
        self.confirm(state, options)
        _, replacement, _ = self.request('POST', '/api/confirmed/new', body={'query': QUERY, 'scenario': 'variant_price'}, **options)
        self.assertNotEqual(replacement['revision'], state['revision'])
        self.assertIsNone(replacement['confirmation'])
        self.assertEqual(self.request('POST', '/api/confirmed/run', body={'revision': state['revision']}, **options)[0], 400)
        self.run_and_trace(self.confirm(replacement, options), options)
        _, other = self.session()
        self.assertEqual(self.request('GET', '/api/confirmed/trace?revision=' + replacement['revision'], cookie=other)[0], 404)
        self.assertEqual(self.request('POST', '/api/confirmed/run', body={'revision': replacement['revision']}, cookie=options['cookie'])[0], 403)

    def test_concurrent_run_uses_one_confirmation_only_once(self):
        state, options = self.start()
        state = self.confirm(state, options)
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda _: self.request('POST', '/api/confirmed/run', body={'revision': state['revision']}, **options)[0], range(2)))
        self.assertEqual(sorted(codes), [200, 400])
        _, after, _ = self.request('GET', '/api/confirmed', cookie=options['cookie'])
        self.assertEqual(after['summary']['physical_requests'], 6)

    def test_page_and_api_cannot_enable_external_models_or_inject_confirmation(self):
        code, html, _ = self.request('GET', '/confirmed')
        self.assertEqual(code, 200)
        self.assertIn('离线假模型', html.decode())
        _, script, _ = self.request('GET', '/confirmed.js')
        self.assertIn(b'draftDirty', script)
        self.assertNotIn(b'innerHTML', script)
        state, options = self.start()
        for body in [{'query': QUERY, 'scenario': 'recovery', 'endpoint': 'https://example.com'},
                     {'query': QUERY, 'scenario': 'recovery', 'confirmation': {'approved': True}}]:
            self.assertEqual(self.request('POST', '/api/confirmed/new', body=body, **options)[0], 400)


if __name__ == '__main__':
    unittest.main()
