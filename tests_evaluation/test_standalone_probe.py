"""Standalone probe security tests with inert fixtures; never real requests."""
import json
import unittest
import warnings
from unittest.mock import patch
import getpass
import relay_probe_standalone as probe

class StandaloneProbeTests(unittest.TestCase):
    def test_success_two_requests_no_secret_or_generated_text(self):
        methods=[]
        def transport(url, method, payload, key):
            methods.append(method)
            if method=='GET':return {'data':[{'id':probe.MODEL}]}
            self.assertEqual(payload['max_tokens'],64)
            return {'model':probe.MODEL,'choices':[{'message':{'content':'private generated content'}}]}
        result=probe.run_probe('inert-fixture-secret',transport=transport)
        self.assertTrue(result['success']);self.assertEqual(methods,['GET','POST'])
        self.assertNotIn('inert-fixture-secret',str(result));self.assertNotIn('private generated',str(result))
    def test_missing_model_and_uncertain_request_never_retry(self):
        result=probe.run_probe('inert-fixture-secret',transport=lambda *args:{'data':[]})
        self.assertEqual(result['physical_attempts'],1);self.assertFalse(result['success'])
        def fail(*args):raise TimeoutError('inert-fixture-secret')
        result=probe.run_probe('inert-fixture-secret',transport=fail)
        self.assertEqual(result['physical_attempts'],1);self.assertNotIn('inert-fixture-secret',str(result))
    def test_unapproved_host_and_redirect_rejected(self):
        with patch('relay_probe_standalone.build_opener') as opener:
            for url in ['http://st.walkcoding.top/v1/models','https://attacker.test/v1/models',
                        'https://st.walkcoding.top:444/v1/models','https://st.walkcoding.top/v1/models?x=1']:
                with self.assertRaises(probe.ProbeError):probe.request(url,'GET',None,'inert-fixture-secret')
            opener.assert_not_called()
        with self.assertRaises(probe.ProbeError):probe.NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.test')
    def test_no_tty_no_prompt(self):
        with patch('sys.stdin.isatty',return_value=False),patch('getpass.getpass') as getter,patch('builtins.print'):
            self.assertEqual(probe.main([]),2);getter.assert_not_called()
    def test_no_echo_fallback(self):
        def fallback(*args):warnings.warn('cannot hide',getpass.GetPassWarning)
        with patch('sys.stdin.isatty',return_value=True),patch('getpass.getpass',side_effect=fallback),patch('builtins.print'):
            self.assertEqual(probe.main([]),2)
    def test_network_response_credential_reflection_discarded(self):
        url='https://st.walkcoding.top/v1/models'
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return url
            def read(self,n):return json.dumps({'echo':'inert-fixture-secret'}).encode()
        with patch('relay_probe_standalone.build_opener') as opener:
            opener.return_value.open.return_value=Response()
            with self.assertRaises(probe.ProbeError):probe.request(url,'GET',None,'inert-fixture-secret')

if __name__=='__main__':unittest.main()
