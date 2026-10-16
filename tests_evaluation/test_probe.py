"""Offline no-echo probe tests; injected inert keys and no network."""
import unittest
from evaluation.probe import probe

class ProbeTests(unittest.TestCase):
    def test_minimal_two_calls_and_no_key_in_result(self):
        calls=[]
        def transport(url,method,payload,headers,timeout):
            calls.append((url,payload))
            if method=='GET':return {'data':[{'id':'gpt-6.1-sol'}]}
            self.assertEqual(payload['max_tokens'],64)
            return {'model':'gpt-6.1-sol','choices':[{'message':{'role':'assistant','content':'OK'}}]}
        result=probe(endpoint='https://st.walkcoding.top/v1/chat/completions',key_reader=lambda:'inert-test-key',transport=transport)
        self.assertTrue(result['success']);self.assertEqual(len(calls),2)
        self.assertNotIn('inert-test-key',str(result));self.assertIsNone(result['cost_usd'])
    def test_unknown_model_stops_without_generation(self):
        calls=[]
        def transport(*args):calls.append(1);return {'data':[]}
        result=probe(endpoint='https://st.walkcoding.top/v1/chat/completions',key_reader=lambda:'inert-test-key',transport=transport)
        self.assertFalse(result['success']);self.assertEqual(len(calls),1)
    def test_no_tty_no_request(self):
        def denied():raise ValueError('no tty')
        result=probe(endpoint='https://st.walkcoding.top/v1/chat/completions',key_reader=denied,
                     transport=lambda *args: self.fail('must not call'))
        self.assertFalse(result['success']);self.assertEqual(result['physical_attempts'],0)

if __name__=='__main__':unittest.main()
