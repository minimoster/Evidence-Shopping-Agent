"""Synthetic relay transport tests; keys below are inert fixture strings."""
import unittest
from evaluation.runner import RunConfig
from evaluation.relay import RelayClient, AttemptAccounting, RelayError, RelayOutcomeUncertain, ExactModelUnavailable, _validate_url, _NoRedirect

class RelayTests(unittest.TestCase):
    def client(self, transport, **kwargs):
        return RelayClient(api_key='fixture-inert-key', endpoint='https://st.walkcoding.top/v1/chat/completions',
            accounting=AttemptAccounting(5), transport=transport, **kwargs)
    def test_host_path_and_redirect_scope(self):
        for url in ['http://st.walkcoding.top/v1/models','https://example.com/v1/models',
                    'https://st.walkcoding.top.attacker.test/v1/models','https://user@st.walkcoding.top/v1/models',
                    'https://st.walkcoding.top/v1/models?key=x','https://st.walkcoding.top:444/v1/models']:
            with self.assertRaises(ValueError): _validate_url(url)
        with self.assertRaises(RelayError): _NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.test')
    def test_discovery_exact_and_response_usage_unknown_dollars(self):
        def transport(url, method, payload, headers, timeout):
            if method == 'GET': return {'data':[{'id':'gpt-6.1-sol'}]}
            self.assertEqual(payload['model'],'gpt-6.1-sol')
            return {'model':'gpt-6.1-sol','choices':[{'message':{'role':'assistant','content':'OK'}}],
                    'usage':{'prompt_tokens':12,'completion_tokens':2,'cost':999}}
        client=self.client(transport); client.verify_exact_model()
        self.assertEqual(client.complete([{'role':'user','content':'Say OK'}],[])['content'],'OK')
        self.assertEqual(client.last_usage,{'input_tokens':12,'output_tokens':2,'cost_usd':None})
        self.assertEqual(len(client.accounting.records),2)
        self.assertNotIn('fixture-inert-key',str(client.accounting.records))
    def test_no_substitution(self):
        client=self.client(lambda *args:{'data':[{'id':'other-model'}]})
        with self.assertRaises(ExactModelUnavailable):client.verify_exact_model()
        with self.assertRaises(ExactModelUnavailable):client.complete([],[])
        self.assertEqual(len(client.accounting.records),1)
    def test_no_retry_on_uncertain_error_or_reflection(self):
        def fail(*args):raise TimeoutError('fixture-inert-key')
        client=self.client(fail)
        with self.assertRaises(RelayOutcomeUncertain) as context:client.verify_exact_model()
        self.assertNotIn('fixture-inert-key',str(context.exception))
        self.assertEqual(len(client.accounting.records),1)
        client=self.client(lambda *args:{'secret':'fixture-inert-key'})
        with self.assertRaises(RelayOutcomeUncertain):client.verify_exact_model()
    def test_finite_attempt_budget_and_clear(self):
        accounting=AttemptAccounting(1); accounting.reserve('first')
        with self.assertRaises(RelayError):accounting.reserve('retry')
        client=self.client(lambda *args:{'data':[{'id':'gpt-6.1-sol'}]});client.close()
        with self.assertRaises(RelayError):client.verify_exact_model()
        self.assertEqual(client.accounting.records,[])
    def test_response_model_mismatch_stops(self):
        client=self.client(lambda *args:{'model':'other','choices':[]});client.model_available=True
        with self.assertRaises(ExactModelUnavailable):client.complete([],[])
        self.assertEqual(len(client.accounting.records),1)

if __name__=='__main__':unittest.main()
