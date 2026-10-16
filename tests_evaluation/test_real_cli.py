"""All transports/runtime calls below are mocked, never real evaluation results."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import getpass
from evaluation.experiment import ExperimentManifest, incomplete_row
from evaluation.runner import RunConfig
from evaluation.relay import RelayClient, AttemptAccounting
from evaluation.real_cli import read_transient_key, run_authorized

class FakeRuntime:
    verified=True
    closed=False
    def env_factory(self, **kwargs): raise AssertionError('must be mocked')
    def close(self): self.closed=True

class RealCliTests(unittest.TestCase):
    def setUp(self):
        self.plan=ExperimentManifest(tuple(range(20)),RunConfig(execution_kind='real_model_real_simulator'))
    def client(self, fail=False):
        def transport(url, method, payload, headers, timeout):
            if fail: raise TimeoutError('inert-test-key')
            if method=='GET':return {'data':[{'id':'gpt-6.1-sol'}]}
            return {'model':'gpt-6.1-sol','choices':[{'message':{'role':'assistant','content':'OK'}}]}
        return RelayClient(api_key='inert-test-key',endpoint='https://st.walkcoding.top/v1/chat/completions',
                           accounting=AttemptAccounting(1802),transport=transport)
    def test_no_redirected_or_echo_fallback_key_input(self):
        with patch('sys.stdin.isatty',return_value=False), patch('getpass.getpass') as getter:
            with self.assertRaises(ValueError):read_transient_key()
            getter.assert_not_called()
        import warnings
        def fallback(*args,**kwargs):warnings.warn('no tty',getpass.GetPassWarning)
        with patch('sys.stdin.isatty',return_value=True), patch('getpass.getpass',side_effect=fallback):
            with self.assertRaises(getpass.GetPassWarning):read_transient_key()
    def test_exact_60_slots_mocked_and_key_closed(self):
        calls=[]
        def task(task_id,client,config,**kwargs):
            calls.append((task_id,config.arm))
            row=incomplete_row(self.plan,task_id,config.arm,status='done')
            row['success']=True;row['purchase_outcome_unknown']=False
            return row
        runtime=FakeRuntime();client=self.client()
        with tempfile.TemporaryDirectory() as tmp,patch('evaluation.real_cli.run_task',side_effect=task),patch('builtins.print'):
            report=run_authorized(self.plan,runtime,client,Path(tmp)/'run')
            self.assertEqual(len(calls),60)
            self.assertEqual(len(client.accounting.records),2)
            self.assertTrue(runtime.closed);self.assertIsNone(client._api_key)
            for arm in 'ABC':self.assertEqual(report['arms'][arm]['tasks'],20)
            self.assertNotIn('inert-test-key',''.join(p.read_text() for p in (Path(tmp)/'run').glob('*.json')))
    def test_connectivity_failure_no_retry_no_task_omission(self):
        client=self.client(fail=True);runtime=FakeRuntime()
        with tempfile.TemporaryDirectory() as tmp,patch('evaluation.real_cli.run_task') as task,patch('builtins.print'):
            report=run_authorized(self.plan,runtime,client,Path(tmp)/'run')
            task.assert_not_called();self.assertEqual(len(client.accounting.records),1)
            for arm in 'ABC':
                self.assertEqual(report['arms'][arm]['tasks'],20)
                self.assertEqual(report['arms'][arm]['aborted_unattempted_rows'],20)
    def test_cleanup_failure_does_not_lose_accounting_or_report(self):
        runtime=FakeRuntime()
        runtime.close=lambda: (_ for _ in ()).throw(RuntimeError('private cleanup error'))
        with tempfile.TemporaryDirectory() as tmp,patch('builtins.print'):
            directory=Path(tmp)/'run'
            report=run_authorized(self.plan,runtime,self.client(fail=True),directory)
            self.assertTrue((directory/'request-accounting.json').exists())
            self.assertTrue((directory/'report.json').exists())
            self.assertNotIn('private cleanup error',str(report))
    def test_first_task_transport_error_stops_remaining_slots(self):
        def task(task_id,client,config,**kwargs):
            row=incomplete_row(self.plan,task_id,config.arm,status='error',error_type='RelayOutcomeUncertain')
            return row
        with tempfile.TemporaryDirectory() as tmp,patch('evaluation.real_cli.run_task',side_effect=task) as call,patch('builtins.print'):
            report=run_authorized(self.plan,FakeRuntime(),self.client(),Path(tmp)/'run')
            self.assertEqual(call.call_count,1)
            self.assertEqual(sum(x['aborted_unattempted_rows'] for x in report['arms'].values()),59)

if __name__=='__main__':unittest.main()
