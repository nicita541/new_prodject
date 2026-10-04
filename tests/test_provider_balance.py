import json
import unittest
from unittest.mock import patch

from app import provider_balance as balance
from app import deepseek
from tests import test_deepseek


def response(amount, **funds):
    return {'is_available':True,'balance_infos':[{'currency':'USD','total_balance':amount,**funds}]}


class ProviderBalanceTests(unittest.TestCase):
    # Reuse isolated workspace settings/runtime fixtures, not billing tests.
    setUp = test_deepseek.DeepSeekTests.setUp
    vision = test_deepseek.DeepSeekTests.vision
    entries = test_deepseek.DeepSeekTests.entries
    def test_provider_decrease_is_not_the_token_ceiling_or_a_key_invoice(self):
        balance.record(response('2'),self.directory,1,True,100)
        balance.record(response('1.97'),self.directory,1,False,110)
        state=balance.status(self.directory,1)
        self.assertEqual(state['window']['decrease_usd'],'0.03')
        self.assertEqual(state['window']['coverage'],'full_attempt')
        self.assertEqual(state['scope'],'account')
        self.assertFalse(self.ledger.exists())

    def test_old_job_and_new_attempt_have_no_fabricated_historical_spending(self):
        balance.record(response('1.9'),self.directory,1,False,100)
        self.assertEqual(balance.status(self.directory,1)['window']['coverage'],'since_observation')
        self.assertIsNone(balance.status(self.directory,2)['window'])
        self.assertIsNone(balance.status(self.directory/'old-job',1)['window'])

    def test_topup_and_fund_adjustments_disable_decrease_even_if_balance_later_drops(self):
        balance.record(response('2',topped_up_balance='2'),self.directory,1,True,100)
        balance.record(response('3',topped_up_balance='3'),self.directory,1,False,110)
        balance.record(response('1.5',topped_up_balance='1.5'),self.directory,1,False,120)
        state=balance.status(self.directory,1)
        self.assertTrue(state['window']['adjusted'])
        self.assertIsNone(state['window']['decrease_usd'])
        self.assertIsNone(state['observed_decrease_usd'])

    def test_old_response_cannot_overwrite_a_newer_observation(self):
        balance.record(response('1.9'),measured_at=110)
        balance.record(response('2'),measured_at=100)
        self.assertEqual(balance.status()['balance_usd'],'1.9')

    def test_refresh_throttles_free_requests_and_never_mutates_ledger(self):
        self.http.return_value=response('2')
        with patch('app.provider_balance.time.time',return_value=1000):
            balance.refresh(self.directory,1)
            balance.refresh(self.directory,1)
        self.http.assert_called_once_with('/user/balance',timeout=8)
        self.assertFalse(self.ledger.exists())

    def test_failure_retains_last_provider_value_and_unknown_charge_guard(self):
        balance.record(response('2'),measured_at=100)
        self.ledger.write_text(json.dumps({'version':1,'halted':True,'entries':[
            {'charged_ceiling_usd':'0.009','status':'unknown','job':'fixture'}]}),'utf-8')
        before=self.ledger.read_bytes()
        self.http.side_effect=deepseek.RemoteError('secret must not be shown')
        with patch('app.provider_balance.time.time',return_value=1000):
            state=balance.refresh()
        self.assertEqual(state['balance_usd'],'2')
        self.assertTrue(state['stale'])
        self.assertNotIn('secret',state['error'])
        self.assertEqual(self.ledger.read_bytes(),before)

    def test_malformed_usd_and_missing_currency_are_not_zero_expense(self):
        for raw in (response('-1'),response('NaN'),{'is_available':True,'balance_infos':[]},
                    {'is_available':True,'balance_infos':[{'currency':'CNY','total_balance':'50'}]}):
            with self.assertRaises(deepseek.RemoteError):balance.record(raw)
        self.assertIsNone(balance.status()['balance_usd'])
        self.assertIsNone(balance.status()['observed_decrease_usd'])

    def test_paid_response_keeps_conservative_cost_and_reports_different_provider_debit(self):
        self.http.side_effect=[response('2'),response('1.97')]
        self.vision().query('new task',schema={'type':'object'})
        state=deepseek.job_spending(self.directory)
        self.assertEqual(state['charged_ceiling_usd'],'0.000042')
        self.assertEqual(state['provider_balance']['window']['decrease_usd'],'0.03')
        self.assertEqual(self.entries()[0]['status'],'completed')
