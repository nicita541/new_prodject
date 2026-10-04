import base64
import copy
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import io
import hashlib
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import uuid

from app import deepseek as api
from app.config import TEMP
from app.jobs import BusyError


SCHEMA = {'type':'object','properties':{'keep':{'type':'array','items':{'type':'string','enum':['u000']}}},
          'required':['keep'],'additionalProperties':False}


def reply(content='{"keep":["u000"]}', incoming=100, outgoing=10):
    return {'usage':{'prompt_tokens':incoming,'completion_tokens':outgoing},
            'choices':[{'message':{'content':content}}]}


class DeepSeekTests(unittest.TestCase):
    def test_extended_text_context_is_explicit_bounded_and_fully_reserved(self):
        prompt='full episode context '*1500
        with self.assertRaises(api.BudgetExceeded):
            self.vision().query(prompt,schema=SCHEMA)
        self.fetch.assert_not_called()
        extended=api.DeepSeekVision(self.directory,lambda:False,text_budget=64000)
        with patch.object(api,'TOTAL_BUDGET',None):
            extended.query(prompt,schema=SCHEMA)
        body=self.fetch.call_args.args[0]
        text_bytes=len((api.SYSTEM+body['messages'][1]['content'][0]['text']).encode('utf-8'))
        expected=(Decimal(text_bytes+512)*api.INPUT_PER_MILLION+Decimal(body['max_tokens'])*api.OUTPUT_PER_MILLION)/1000000
        self.assertEqual(Decimal(self.entries()[0]['reserved_usd']),expected)
        for invalid in (64001,19999,True):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                api.DeepSeekVision(self.directory,lambda:False,text_budget=invalid)

    def test_image_pages_are_bounded_reserved_and_cached_by_every_page(self):
        pages=[self.directory/'page1.jpg',self.directory/'page2.jpg']
        pages[0].write_bytes(b'first pixels');pages[1].write_bytes(b'second pixels')
        vision=self.vision()
        vision.query('chronological pages',pages,max_tokens=100,schema=SCHEMA)
        body=self.fetch.call_args.args[0]
        content=body['messages'][1]['content']
        self.assertEqual([base64.b64decode(item['image_url']['url'].split(',')[1]) for item in content[1:]],
                         [b'first pixels',b'second pixels'])
        text_bytes=len((api.SYSTEM+content[0]['text']).encode('utf-8'))
        expected=(Decimal(text_bytes+512+2048)*api.INPUT_PER_MILLION+Decimal(body['max_tokens'])*api.OUTPUT_PER_MILLION)/1000000
        self.assertEqual(Decimal(self.entries()[0]['reserved_usd']),expected)
        vision.query('chronological pages',pages,max_tokens=100,schema=SCHEMA)
        self.assertEqual(self.fetch.call_count,1)
        pages[1].write_bytes(b'changed second page')
        vision.query('chronological pages',pages,max_tokens=100,schema=SCHEMA)
        self.assertEqual(self.fetch.call_count,2)

    def test_invalid_image_pages_never_fetch_or_reserve(self):
        page=self.directory/'page.jpg';page.write_bytes(b'pixels')
        for pages in ([],[page]*9,[page,Path('F:/outside-workspace.jpg')]):
            with self.subTest(pages=pages),self.assertRaises(ValueError):
                self.vision().query('invalid pages',pages,schema=SCHEMA)
        self.fetch.assert_not_called();self.http.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_production_reasoning_is_explicit_and_has_separate_paid_cache(self):
        ordinary=self.vision()
        ordinary.query('same analysis task',max_tokens=800,schema=SCHEMA)
        normal=self.fetch.call_args.args[0]
        self.assertEqual(normal['thinking'],{'type':'disabled'})
        thinking=api.DeepSeekVision(self.directory,lambda:False,reasoning_effort='low')
        with patch.object(api,'TOTAL_BUDGET',None):
            thinking.query('same analysis task',max_tokens=8192,schema=SCHEMA)
        body=self.fetch.call_args.args[0]
        self.assertEqual(body['thinking'],{'type':'enabled'})
        self.assertEqual(body['reasoning_effort'],'low')
        self.assertNotIn('temperature',body)
        self.assertEqual(body['max_tokens'],8192)
        self.assertEqual(self.fetch.call_count,2)
        thinking.query('same analysis task',max_tokens=8192,schema=SCHEMA)
        self.assertEqual(self.fetch.call_count,2)

    def test_new_attempt_renews_limit_without_erasing_cost_or_unblocking_requests(self):
        key = api.job_key(self.directory)
        self.ledger.write_text(json.dumps({'version':1, 'halted':False, 'blocked_requests':['never-replay'],
            'entries':[{'job':key,'request':'earlier','status':'acknowledged_unknown',
                        'charged_ceiling_usd':'0.099','reserved_usd':'0.099'}]}), encoding='utf-8')
        with patch.object(api, 'TOTAL_BUDGET', None):
            previous = api.public_status()['charged_ceiling_usd']
            result = api.begin_attempt(self.directory)
            self.assertEqual(result['attempt'], 2)
            self.assertEqual(result['charged_ceiling_usd'], '0')
            self.assertIsNone(result['remaining_usd'])
            self.assertIsNone(result['limit_usd'])
            self.assertEqual(result['job_total_usd'], '0.099')
            self.assertEqual(api.public_status()['charged_ceiling_usd'], previous)
            self.assertEqual(json.loads(self.ledger.read_text('utf-8'))['blocked_requests'], ['never-replay'])
            self.vision().query('new task in fresh attempt', schema=SCHEMA)
            self.assertEqual(self.entries()[-1]['attempt'], 2)
            self.assertEqual(api.job_spending(self.directory)['charged_ceiling_usd'], '0.000042')

    def test_default_has_no_ten_cent_limit_and_preserves_accounting(self):
        key = api.job_key(self.directory)
        self.ledger.write_text(json.dumps({'version':1,'entries':[{'job':key,'request':'earlier',
            'status':'completed','charged_ceiling_usd':'0.15','reserved_usd':'0.15'}]}),encoding='utf-8')
        with patch.object(api,'TOTAL_BUDGET',None):
            self.vision().query('ordinary new request after fifteen cents',schema=SCHEMA)
        self.assertEqual(self.fetch.call_count,1)
        state=api.job_spending(self.directory)
        self.assertIsNone(state['limit_usd'])
        self.assertIsNone(state['remaining_usd'])
        self.assertEqual(state['charged_ceiling_usd'],'0.150042')

    def test_attempt_reset_preserves_global_unknown_billing_halt(self):
        self.fetch.side_effect = api.RemoteError('connection interrupted')
        with self.assertRaises(api.RemoteError):
            self.vision().query('uncertain task', schema=SCHEMA)
        before = self.entries()
        api.begin_attempt(self.directory)
        self.assertEqual(self.entries(), before)
        self.assertTrue(json.loads(self.ledger.read_text('utf-8'))['halted'])
        self.fetch.reset_mock()
        with self.assertRaises(api.BudgetExceeded):
            self.vision().query('new task', schema=SCHEMA)
        self.fetch.assert_not_called()

    def test_per_episode_limit_includes_uncertain_reserves_and_survives_resume(self):
        key = api.job_key(self.directory)
        self.ledger.write_text(json.dumps({'version':1,'entries':[{'job':key,'request':'earlier',
            'status':'acknowledged_unknown','charged_ceiling_usd':'0.099','reserved_usd':'0.099'}]}), encoding='utf-8')
        with patch.object(api,'TOTAL_BUDGET',None), patch.object(api,'EPISODE_BUDGET',Decimal('0.10')):
            with self.assertRaises(api.EpisodeBudgetExceeded):
                self.vision().query('new expensive task',schema=SCHEMA)
            self.fetch.assert_not_called()
            self.http.assert_not_called()
            self.assertEqual(api.job_spending(self.directory)['charged_ceiling_usd'],'0.099')
            other = self.directory / 'another-episode'
            other.mkdir()
            api.DeepSeekVision(other,lambda:False).query('different episode',schema=SCHEMA)
            self.assertEqual(self.fetch.call_count,1)

    def test_acknowledged_unknown_retains_cost_blocks_replay_and_allows_only_new_tasks(self):
        self.fetch.side_effect = api.RemoteError('connection interrupted')
        with self.assertRaises(api.RemoteError):
            self.vision().query('unknown task', max_tokens=20, schema=SCHEMA)
        before = self.entries()[0].copy()
        connection = {'available':True, 'vision_supported':True,
                      'balance_infos':[{'currency':'USD','total_balance':'2.03'}]}
        with patch.object(api, 'check_connection', return_value=connection):
            self.assertTrue(api.acknowledge_reserved_requests()['resumed'])
        after = self.entries()[0]
        self.assertEqual(after['charged_ceiling_usd'], before['charged_ceiling_usd'])
        self.assertEqual(after['status'], 'acknowledged_unknown')
        self.assertNotIn('usage', after)
        self.assertTrue(after['reservation_retained'])
        self.fetch.reset_mock()
        self.fetch.side_effect = None
        self.fetch.return_value = reply()
        with self.assertRaises(api.AlreadyPaidInvalidResponse):
            self.vision().query('unknown task', max_tokens=20, schema=SCHEMA)
        self.fetch.assert_not_called()
        self.vision().query('different new task', max_tokens=20, schema=SCHEMA)
        self.assertEqual(self.fetch.call_count, 1)

    def test_acknowledgment_cannot_reopen_without_live_available_funds(self):
        self.fetch.side_effect = api.RemoteError('connection interrupted')
        with self.assertRaises(api.RemoteError):
            self.vision().query('unknown task', max_tokens=20, schema=SCHEMA)
        before = self.ledger.read_bytes()
        with patch.object(api, 'check_connection', return_value={'available':False, 'vision_supported':True}):
            with self.assertRaises(api.RemoteError):
                api.acknowledge_reserved_requests()
        self.assertEqual(self.ledger.read_bytes(), before)

    def setUp(self):
        # Ordinary mkdir avoids the restricted Windows ACL of TemporaryDirectory.
        # Every path and secret below belongs to this test, never real settings.
        self.directory=TEMP/('deepseek_test_'+uuid.uuid4().hex)
        self.directory.mkdir()
        self.settings=self.directory/'settings'
        self.settings.mkdir()
        self.private=self.settings/'fake.private.json'
        self.ledger=self.settings/'fake-spending.json'
        self.responses=self.directory/'responses'
        self.fake_key='sk-fake-tests-only-'+uuid.uuid4().hex
        self.private.write_text(json.dumps({'api_key':self.fake_key}),encoding='utf-8')
        self.real_http=api._http
        self.http=Mock(return_value={'is_available':True,'balance_infos':[{'currency':'USD','total_balance':'0.06'}]})
        self.fetch=Mock(return_value=reply())
        for name,value in [('SETTINGS',self.settings),('PRIVATE',self.private),('LEDGER',self.ledger),('RESPONSES',self.responses),
                           ('_http',self.http),('TOTAL_BUDGET',Decimal('0.01'))]:
            patcher=patch.object(api,name,value)
            patcher.start()
            self.addCleanup(patcher.stop)
        fetch_patcher=patch.object(api.DeepSeekVision,'_fetch',self.fetch)
        fetch_patcher.start()
        self.addCleanup(fetch_patcher.stop)

    def vision(self,cancelled=lambda:False):
        return api.DeepSeekVision(self.directory,cancelled)

    def entries(self):
        return json.loads(self.ledger.read_text('utf-8'))['entries']

    def reset_fake_ledger(self):
        # Subcases represent independent accounts; only this UUID fixture is reset.
        self.ledger.unlink(missing_ok=True)

    def legacy_digest(self, body, prompt, schema, max_tokens=1200):
        legacy=copy.deepcopy(body)
        legacy['max_tokens']=max_tokens
        legacy['messages'][1]['content'][0]['text']=prompt+'\nReturn JSON exactly matching this schema: '+json.dumps(schema,ensure_ascii=False)
        return hashlib.sha256(json.dumps({'profile':api.PROFILE,'request':legacy},
            sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()

    def test_schema_prompt_explicitly_requests_actual_values_and_unseen_request_succeeds(self):
        self.assertEqual(self.vision().query('new unseen scene',schema=SCHEMA),{'keep':['u000']})
        body=self.fetch.call_args.args[0]
        text=body['messages'][1]['content'][0]['text']
        self.assertIn('schema is a specification, DO NOT output it',text)
        self.assertIn('concrete JSON instance with actual values',text)
        self.assertIn('Do not return schema definitions or type/properties/enum keys',text)
        self.assertIn('compact JSON only, no explanation',text)
        self.assertIn(json.dumps(SCHEMA,ensure_ascii=False),text)
        self.fetch.assert_called_once()

    def test_legacy_successful_cache_with_image_remains_usable_without_key_balance_or_payment(self):
        image=self.directory/'legacy-frame.jpg'
        image.write_bytes(b'legacy image pixels')
        expected=self.vision().query('existing scene',image,schema=SCHEMA)
        body=self.fetch.call_args.args[0]
        legacy=self.legacy_digest(body,'existing scene',SCHEMA)
        current=self.entries()[0]['request']
        self.assertNotEqual(current,legacy)
        (self.responses/(current+'.json')).replace(self.responses/(legacy+'.json'))
        self.private.unlink()
        self.http.reset_mock()
        self.fetch.reset_mock()
        cached=api.DeepSeekVision(self.directory,lambda:False,cache_only=True)
        self.assertEqual(cached.query('existing scene',image,schema=SCHEMA),expected)
        self.http.assert_not_called()
        self.fetch.assert_not_called()
        self.assertEqual(len(self.entries()),1)

    def test_legacy_blocked_paid_failure_cannot_be_repaid_after_prompt_wording_change(self):
        self.fetch.return_value=reply('{"keep":["invented"]}')
        with self.assertRaises(api.RemoteError):
            self.vision().query('previous rejected scene',schema=SCHEMA)
        legacy=self.legacy_digest(self.fetch.call_args.args[0],'previous rejected scene',SCHEMA)
        ledger=json.loads(self.ledger.read_text('utf-8'))
        ledger['halted']=False
        ledger['entries'][0]['request']=legacy
        ledger['blocked_requests']=[legacy]
        self.ledger.write_text(json.dumps(ledger),encoding='utf-8')
        self.http.reset_mock()
        self.fetch.reset_mock()
        with self.assertRaises(api.AlreadyPaidInvalidResponse):
            self.vision().query('previous rejected scene',schema=SCHEMA)
        self.http.assert_not_called()
        self.fetch.assert_not_called()
        self.assertEqual(len(self.entries()),1)

    def test_legacy_cache_still_requires_current_strict_schema_validation(self):
        self.vision().query('invalid legacy cache',schema=SCHEMA)
        body=self.fetch.call_args.args[0]
        legacy=self.legacy_digest(body,'invalid legacy cache',SCHEMA)
        current=self.entries()[0]['request']
        (self.responses/(current+'.json')).unlink()
        (self.responses/(legacy+'.json')).write_text(json.dumps({'result':{'keep':['invented']}}),encoding='utf-8')
        cached=api.DeepSeekVision(self.directory,lambda:False,cache_only=True)
        self.http.reset_mock()
        self.fetch.reset_mock()
        with self.assertRaises(api.BudgetExceeded):
            cached.query('invalid legacy cache',schema=SCHEMA)
        self.http.assert_not_called()
        self.fetch.assert_not_called()

    def test_answer_budget_mapping_and_reservation_use_effective_allowance(self):
        expected={1:512,130:512,400:512,401:2048,650:2048,800:2048,
                  801:3072,1200:3072,1400:3072,1401:4096,1800:4096,1801:4096,8192:8192,16384:16384}
        for requested,effective in expected.items():
            with self.subTest(requested=requested),patch.object(api,'TOTAL_BUDGET',None):
                self.reset_fake_ledger()
                self.assertEqual(api.answer_budget(requested),effective)
                self.fetch.return_value=reply(incoming=100,outgoing=effective)
                self.vision().query('allowance '+str(requested),max_tokens=requested,schema=SCHEMA)
                body=self.fetch.call_args.args[0]
                self.assertEqual(body['max_tokens'],effective)
                text=body['messages'][1]['content'][0]['text']
                incoming_bound=len((api.SYSTEM+text).encode('utf-8'))+512
                expected_reservation=(Decimal(incoming_bound)*api.INPUT_PER_MILLION
                    +Decimal(effective)*api.OUTPUT_PER_MILLION)/1000000
                self.assertEqual(Decimal(self.entries()[0]['reserved_usd']),expected_reservation)
                self.assertEqual(self.entries()[0]['usage']['completion_tokens'],effective)

    def test_prior_instance_instruction_cache_is_reused_with_original_caller_allowance(self):
        requested=130
        expected=self.vision().query('previous instance prompt',max_tokens=requested,schema=SCHEMA)
        old_body=copy.deepcopy(self.fetch.call_args.args[0])
        old_body['max_tokens']=requested
        previous=hashlib.sha256(json.dumps({'profile':api.PROFILE,'request':old_body},
            sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
        current=self.entries()[0]['request']
        self.assertNotEqual(previous,current)
        (self.responses/(current+'.json')).replace(self.responses/(previous+'.json'))
        self.http.reset_mock()
        self.fetch.reset_mock()
        cached=api.DeepSeekVision(self.directory,lambda:False,cache_only=True)
        self.assertEqual(cached.query('previous instance prompt',max_tokens=requested,schema=SCHEMA),expected)
        self.http.assert_not_called()
        self.fetch.assert_not_called()

    def test_both_prior_paid_failure_identities_stay_blocked_when_allowance_increases(self):
        for requested in (130,650,1800):
            for style in ('legacy_schema','previous_instance'):
                with self.subTest(requested=requested,style=style):
                    self.reset_fake_ledger()
                    prompt='prior failed '+str(requested)+' '+style
                    self.fetch.return_value=reply('{"keep":["invented"]}')
                    with self.assertRaises(api.RemoteError):
                        self.vision().query(prompt,max_tokens=requested,schema=SCHEMA)
                    actual=copy.deepcopy(self.fetch.call_args.args[0])
                    old=copy.deepcopy(actual)
                    old['max_tokens']=requested
                    if style=='legacy_schema':
                        old['messages'][1]['content'][0]['text']=prompt+'\nReturn JSON exactly matching this schema: '+json.dumps(SCHEMA,ensure_ascii=False)
                    previous=hashlib.sha256(json.dumps({'profile':api.PROFILE,'request':old},
                        sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
                    ledger=json.loads(self.ledger.read_text('utf-8'))
                    ledger.update(halted=False,blocked_requests=[previous])
                    ledger['entries'][0]['request']=previous
                    self.ledger.write_text(json.dumps(ledger),encoding='utf-8')
                    self.http.reset_mock()
                    self.fetch.reset_mock()
                    with self.assertRaises(api.AlreadyPaidInvalidResponse):
                        self.vision().query(prompt,max_tokens=requested,schema=SCHEMA)
                    self.http.assert_not_called()
                    self.fetch.assert_not_called()
                    self.assertEqual(len(self.entries()),1)

    def test_no_automatic_total_limit_and_verified_balance_still_protects_request(self):
        with patch.object(api, 'TOTAL_BUDGET', None):
            self.assertIsNone(api.public_status()['budget_usd'])
            self.fetch.return_value = reply(incoming=17000, outgoing=1000)
            for index in range(2):
                self.vision().query('x'*18000+str(index), max_tokens=1800, schema=SCHEMA)
            self.assertGreater(Decimal(api.public_status()['charged_ceiling_usd']), Decimal('.01'))
            self.assertEqual(api.public_status()['remaining_usd'], '0.06')
            self.http.return_value = {'is_available':True, 'balance_infos':[{'currency':'USD','total_balance':'0.000001'}]}
            before = self.fetch.call_count
            with self.assertRaises(api.BudgetExceeded):
                self.vision().query('not enough balance', schema=SCHEMA)
            self.assertEqual(self.fetch.call_count, before)
            self.assertEqual(api.public_status()['remaining_usd'], '0.000001')

    def test_cache_only_verification_never_spends_or_fetches_balance(self):
        cached = api.DeepSeekVision(self.directory, lambda: False, cache_only=True)
        with self.assertRaises(api.BudgetExceeded):
            cached.query('verified repeat', schema=SCHEMA)
        self.http.assert_not_called()
        self.fetch.assert_not_called()
        expected = self.vision().query('verified repeat', schema=SCHEMA)
        before = self.entries()
        self.http.reset_mock()
        self.fetch.reset_mock()
        self.assertEqual(cached.query('verified repeat', schema=SCHEMA), expected)
        self.assertEqual(self.entries(), before)
        self.http.assert_not_called()
        self.fetch.assert_not_called()

    def test_reservation_is_durable_before_paid_post_and_settles_actual_usage(self):
        def posted(body):
            entries=self.entries()
            self.assertEqual(len(entries),1)
            self.assertEqual(entries[0]['status'],'reserved')
            self.assertEqual(entries[0]['reserved_usd'],entries[0]['charged_ceiling_usd'])
            self.assertGreater(Decimal(entries[0]['reserved_usd']),0)
            self.assertNotIn(self.fake_key,json.dumps(body))
            return reply()
        self.fetch.side_effect=posted
        self.assertEqual(self.vision().query('source facts',schema=SCHEMA),{'keep':['u000']})
        entry=self.entries()[0]
        self.assertEqual(entry['status'],'completed')
        self.assertEqual(Decimal(entry['charged_ceiling_usd']),Decimal('0.000042'))
        self.fetch.assert_called_once()

    def test_total_cap_survives_new_instances_and_unique_requests(self):
        self.fetch.return_value=reply(incoming=200,outgoing=1800)
        for index in range(3):
            self.vision().query('request '+str(index),max_tokens=1800,schema=SCHEMA)
        with self.assertRaises(api.BudgetExceeded):
            self.vision().query('another job',max_tokens=1800,schema=SCHEMA)
        self.assertEqual(self.fetch.call_count,3)
        used=sum(Decimal(e['charged_ceiling_usd']) for e in self.entries())
        self.assertEqual(used,Decimal('0.00666'))
        self.assertLessEqual(used,api.TOTAL_BUDGET)
        self.assertEqual(api.public_status()['charged_ceiling_usd'],str(used))

    def test_unknown_failure_preserves_reservation_and_never_retries(self):
        self.fetch.side_effect=api.RemoteError('Simulated unknown provider failure')
        with self.assertRaises(api.RemoteError):
            self.vision().query('failed request',schema=SCHEMA)
        entry=self.entries()[0]
        self.assertEqual(entry['status'],'unknown')
        self.assertEqual(entry['charged_ceiling_usd'],entry['reserved_usd'])
        self.fetch.assert_called_once()
        self.assertFalse(list(self.responses.glob('*.json')))
        self.assertEqual(api.public_status()['remaining_usd'],'0')
        self.http.reset_mock()
        self.fetch.reset_mock()
        with self.assertRaises(api.BudgetExceeded):
            self.vision().query('new instance after unknown failure')
        self.http.assert_not_called()
        self.fetch.assert_not_called()

    def test_cached_result_has_no_balance_or_paid_requests_even_at_cap(self):
        expected=self.vision().query('same source',schema=SCHEMA)
        self.ledger.write_text(json.dumps({'version':1,'entries':[{'charged_ceiling_usd':'0.01'}]}),encoding='utf-8')
        self.http.reset_mock()
        self.fetch.reset_mock()
        result=self.vision().query('same source',schema=SCHEMA)
        self.assertEqual(result,expected)
        self.http.assert_not_called()
        self.fetch.assert_not_called()
        self.assertEqual(self.entries(),[{'charged_ceiling_usd':'0.01'}])

    def test_cache_identity_changes_with_pixels_schema_and_profile(self):
        image=self.directory/'русский кадр.jpg'
        image.write_bytes(b'fake JPEG one')
        self.vision().query('facts',image,schema=SCHEMA)
        image.write_bytes(b'fake JPEG two')
        self.vision().query('facts',image,schema=SCHEMA)
        alternative={**SCHEMA,'description':'Different source validation'}
        self.vision().query('facts',image,schema=alternative)
        with patch.object(api,'PROFILE',api.PROFILE+'-changed'):
            self.vision().query('facts',image,schema=SCHEMA)
        self.assertEqual(self.fetch.call_count,4)
        self.assertEqual(len(list(self.responses.glob('*.json'))),4)
        body=self.fetch.call_args.args[0]
        url=body['messages'][1]['content'][1]['image_url']['url']
        self.assertEqual(base64.b64decode(url.split(',',1)[1]),b'fake JPEG two')

    def test_malformed_usage_counters_keep_full_reservation(self):
        for usage in ({}, {'prompt_tokens':True,'completion_tokens':1},
                      {'prompt_tokens':1,'completion_tokens':-1},
                      {'prompt_tokens':1.5,'completion_tokens':1}):
            with self.subTest(usage=usage):
                self.reset_fake_ledger()
                self.fetch.return_value={**reply(),'usage':usage}
                before=len(self.entries()) if self.ledger.exists() else 0
                with self.assertRaises(api.RemoteError):
                    self.vision().query('bad usage '+str(before),max_tokens=20)
                self.assertEqual(self.entries()[-1]['status'],'unknown_usage')
                self.assertEqual(len(self.entries()),before+1)

    def test_nonobject_usage_fails_safely_without_retry(self):
        for usage in (None,[], 'invalid'):
            with self.subTest(usage=usage):
                self.reset_fake_ledger()
                self.fetch.return_value={**reply(),'usage':usage}
                with self.assertRaises(api.RemoteError):
                    self.vision().query('nonobject '+str(usage),max_tokens=20)
                self.assertEqual(self.entries()[-1]['status'],'unknown_usage')

    def test_malformed_json_and_schema_fail_as_remote_errors_without_paid_retry(self):
        for content in ('not JSON','[]','{"keep":["invented"]}', '{"keep":true}', '{"keep":[],"extra":1}'):
            with self.subTest(content=content):
                self.reset_fake_ledger()
                self.fetch.return_value=reply(content)
                before=self.fetch.call_count
                with self.assertRaises(api.RemoteError):
                    self.vision().query('malformed '+content,max_tokens=20,schema=SCHEMA)
                self.assertEqual(self.fetch.call_count,before+1)
                self.assertEqual(self.entries()[-1]['status'],'completed')
        self.assertFalse(list(self.responses.glob('*.json')))

    def test_missing_choices_and_nonstring_content_fail_with_reserved_charge_accounted(self):
        for raw in ({'usage':reply()['usage']}, {**reply(),'choices':[]},reply({'unexpected':'object'})):
            with self.subTest(raw=raw):
                self.reset_fake_ledger()
                self.fetch.return_value=raw
                with self.assertRaises(api.RemoteError):
                    self.vision().query('missing choice '+str(self.fetch.call_count),max_tokens=20)
                self.assertEqual(self.entries()[-1]['status'],'completed')

    def test_overbound_usage_is_recorded_and_blocks_later_spending(self):
        self.fetch.return_value=reply(incoming=100000,outgoing=10)
        with self.assertRaises(api.BudgetExceeded):
            self.vision().query('overbound')
        self.assertGreater(Decimal(self.entries()[0]['charged_ceiling_usd']),api.TOTAL_BUDGET)
        self.fetch.reset_mock()
        with self.assertRaises(api.BudgetExceeded):
            self.vision().query('later request')
        self.fetch.assert_not_called()

    def test_unavailable_or_insufficient_balance_prevents_reservation_and_post(self):
        for balance in ({'is_available':False,'balance_infos':[]},
                        {'is_available':True,'balance_infos':[{'currency':'USD','total_balance':'0'}]}):
            with self.subTest(balance=balance):
                self.http.return_value=balance
                with self.assertRaises(api.BudgetExceeded):
                    self.vision().query('no funds')
                self.fetch.assert_not_called()
                self.assertEqual(self.entries(), [])

    def test_invalid_ledger_stops_calls_instead_of_resetting_budget(self):
        for data in ('invalid JSON', json.dumps({'version':1,'entries':[{'charged_ceiling_usd':'NaN'}]}),
                     json.dumps({'version':1,'entries':[{'charged_ceiling_usd':'-1'}]}),
                     json.dumps({'version':999,'entries':[]})):
            with self.subTest(data=data):
                self.ledger.write_text(data,encoding='utf-8')
                with self.assertRaises(api.RemoteError):
                    self.vision().query('corrupt ledger')
                self.http.assert_not_called()
                self.fetch.assert_not_called()

    def test_ledger_write_must_succeed_before_post(self):
        with patch.object(api,'atomic_json',side_effect=PermissionError('simulated write failure')):
            with self.assertRaises(PermissionError):
                self.vision().query('cannot reserve')
        self.fetch.assert_not_called()

    def test_cancel_before_send_releases_only_unsent_reservation(self):
        calls=0
        def cancelled():
            nonlocal calls
            calls+=1
            return calls>=3
        with self.assertRaises(InterruptedError):
            self.vision(cancelled).query('unsent cancellation')
        entry=self.entries()[0]
        self.assertEqual(entry['status'],'cancelled_before_send')
        self.assertEqual(entry['charged_ceiling_usd'],'0')
        self.fetch.assert_not_called()

    def test_cancel_after_send_keeps_reservation(self):
        self.fetch.side_effect=InterruptedError('simulated cancellation during request')
        with self.assertRaises(InterruptedError):
            self.vision().query('sent cancellation')
        self.assertEqual(self.entries()[0]['status'],'unknown')
        self.assertGreater(Decimal(self.entries()[0]['charged_ceiling_usd']),0)
        self.fetch.assert_called_once()

    def test_concurrent_clients_cannot_reserve_or_send_twice(self):
        entered,release=threading.Event(),threading.Event()
        def posted(body):
            self.assertEqual(self.entries()[0]['status'],'reserved')
            entered.set()
            if not release.wait(4):
                raise RuntimeError('test timeout')
            return reply()
        self.fetch.side_effect=posted
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.vision().query,'first concurrent')
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaises(BusyError):
                    self.vision().query('second concurrent')
            finally:
                release.set()
            self.assertEqual(future.result(timeout=4),{'keep':['u000']})
        self.assertEqual(self.fetch.call_count,1)
        self.assertEqual(len(self.entries()),1)

    def test_outside_workspace_and_oversize_images_never_send_requests(self):
        with self.assertRaises(ValueError):
            self.vision().query('outside',Path('C:/outside-test-image-never-read.jpg'))
        large=self.directory/'too-large.jpg'
        with large.open('wb') as stream:
            stream.truncate(4*1024**2+1)
        with self.assertRaises(ValueError):
            self.vision().query('oversize',large)
        self.fetch.assert_not_called()
        self.http.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_redirects_proxy_and_http_errors_never_expose_fake_secret(self):
        opener=Mock()
        opener.open.side_effect=urllib.error.HTTPError('https://api.deepseek.com/chat/completions',401,'bad',{},
            io.BytesIO(('echo '+self.fake_key).encode()))
        with patch.object(api.urllib.request,'build_opener',return_value=opener) as build:
            with self.assertRaises(api.RemoteError) as caught:
                self.real_http('/chat/completions',{'fake':'prompt'})
        self.assertNotIn(self.fake_key,str(caught.exception))
        self.assertIn('401',str(caught.exception))
        self.assertEqual(build.call_args.args[0].proxies,{})
        self.assertIsInstance(build.call_args.args[1],api._NoRedirect)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'),'Bearer '+self.fake_key)
        with self.assertRaises(api.RemoteError):
            api._NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_status_ledger_and_response_cache_never_persist_secret(self):
        self.vision().query('normal request',schema=SCHEMA)
        status=api.public_status()
        self.assertTrue(status['configured'])
        self.assertNotIn(self.fake_key,json.dumps(status))
        for path in [self.ledger,*self.responses.glob('*.json')]:
            text=path.read_text('utf-8')
            self.assertNotIn(self.fake_key,text)
            self.assertNotIn('Bearer ',text)

    def test_invalid_token_bounds_and_huge_prompt_stop_without_calls(self):
        for maximum in (0,16385,True,1.5):
            with self.subTest(maximum=maximum):
                with self.assertRaises(ValueError):
                    self.vision().query('invalid',max_tokens=maximum)
        with self.assertRaises(api.BudgetExceeded):
            self.vision().query('я'*11000)
        self.fetch.assert_not_called()
        self.http.assert_not_called()

    def test_provider_identity_and_token_count_need_no_key_or_network(self):
        self.private.unlink()
        self.assertEqual(api.provider_identity('local'),{'provider':'local'})
        self.assertEqual(api.provider_identity('deepseek')['profile'],api.PROFILE)
        self.assertGreaterEqual(self.vision().token_count('Русский текст'),len('Русский текст'.encode('utf-8')))
        self.http.assert_not_called()
        self.fetch.assert_not_called()

    def test_nonfinite_schema_numbers_and_huge_integers_halt_without_retry(self):
        number_schema={'type':'object','properties':{'confidence':{'type':'number'}},
                       'required':['confidence'],'additionalProperties':False}
        for content in ('{"confidence":NaN}','{"confidence":Infinity}','{"confidence":'+str(10**400)+'}'):
            with self.subTest(content_prefix=content[:32]):
                self.reset_fake_ledger()
                self.fetch.return_value=reply(content)
                before=self.fetch.call_count
                with self.assertRaises(api.RemoteError):
                    self.vision().query('huge numbers '+str(before),max_tokens=500,schema=number_schema)
                self.assertTrue(json.loads(self.ledger.read_text('utf-8'))['halted'])
                self.assertEqual(self.fetch.call_count,before+1)

    def test_usage_optional_fields_cannot_persist_echoed_fake_secret(self):
        raw=reply()
        raw['usage'].update(prompt_cache_hit_tokens=100,prompt_cache_miss_tokens=0,echoed_header=self.fake_key)
        self.fetch.return_value=raw
        self.vision().query('usage sanitization')
        for path in [self.ledger,*self.responses.glob('*.json')]:
            self.assertNotIn(self.fake_key,path.read_text('utf-8'))
        self.assertEqual(self.entries()[0]['usage']['prompt_cache_hit_tokens'],100)

    def test_successful_cache_is_usable_when_ledger_halted_without_network(self):
        expected=self.vision().query('previous good response',schema=SCHEMA)
        ledger=json.loads(self.ledger.read_text('utf-8'))
        ledger['halted']=True
        self.ledger.write_text(json.dumps(ledger),encoding='utf-8')
        self.http.reset_mock()
        self.fetch.reset_mock()
        self.assertEqual(self.vision().query('previous good response',schema=SCHEMA),expected)
        self.http.assert_not_called()
        self.fetch.assert_not_called()

    def test_crashed_process_reservation_stops_resume_before_balance_or_post(self):
        self.ledger.write_text(json.dumps({'version':1,'entries':[{'status':'reserved',
            'charged_ceiling_usd':'0.002','reserved_usd':'0.002','request':'previous-crashed-request'}]}),encoding='utf-8')
        with self.assertRaises(api.BudgetExceeded):
            self.vision().query('resume of unfinished request')
        ledger=json.loads(self.ledger.read_text('utf-8'))
        self.assertTrue(ledger['halted'])
        self.assertEqual(ledger['entries'][0]['charged_ceiling_usd'],'0.002')
        self.http.assert_not_called()
        self.fetch.assert_not_called()

    def test_nonstandard_json_constants_without_schema_are_remote_failures(self):
        for constant in ('NaN','Infinity','-Infinity','1e309'):
            with self.subTest(constant=constant):
                self.reset_fake_ledger()
                self.fetch.return_value=reply('{"unknown":'+constant+'}')
                before=self.fetch.call_count
                with self.assertRaises(api.RemoteError):
                    self.vision().query('nonstandard JSON '+constant,max_tokens=20)
                self.assertTrue(json.loads(self.ledger.read_text('utf-8'))['halted'])
                self.assertEqual(self.fetch.call_count,before+1)

    def test_explicit_recovery_preserves_known_cost_and_blocks_rejected_paid_request(self):
        self.fetch.return_value = reply('{"keep":["invented"]}')
        with self.assertRaises(api.RemoteError):
            self.vision().query('rejected paid request', max_tokens=20, schema=SCHEMA)
        used = api.public_status()['charged_ceiling_usd']
        result = api.resume_confirmed_requests()
        self.assertTrue(result['resumed'])
        self.assertEqual(result['charged_ceiling_usd'], used)
        before = self.fetch.call_count
        with self.assertRaises(api.AlreadyPaidInvalidResponse):
            self.vision().query('rejected paid request', max_tokens=20, schema=SCHEMA)
        self.assertEqual(self.fetch.call_count, before)
        self.fetch.return_value = reply()
        self.vision().query('different authorized request', max_tokens=20, schema=SCHEMA)
        self.assertEqual(self.fetch.call_count, before + 1)

    def test_paid_invalid_response_is_a_quality_error_but_global_halt_remains_budget_error(self):
        self.assertTrue(issubclass(api.AlreadyPaidInvalidResponse,api.RemoteError))
        self.assertFalse(issubclass(api.AlreadyPaidInvalidResponse,api.BudgetExceeded))
        self.fetch.return_value=reply('{"keep":["invented"]}')
        with self.assertRaises(api.RemoteError):
            self.vision().query('known rejected',max_tokens=20,schema=SCHEMA)
        api.resume_confirmed_requests()
        ledger=json.loads(self.ledger.read_text('utf-8'))
        ledger['halted']=True
        self.ledger.write_text(json.dumps(ledger),encoding='utf-8')
        self.http.reset_mock()
        self.fetch.reset_mock()
        with self.assertRaises(api.BudgetExceeded):
            self.vision().query('known rejected',max_tokens=20,schema=SCHEMA)
        self.http.assert_not_called()
        self.fetch.assert_not_called()

    def test_rejected_response_diagnostics_store_only_bounded_safe_fields_and_validated_usage(self):
        raw=reply('not JSON '+self.fake_key+' '+'x'*25000,incoming=100,outgoing=130)
        raw['choices'][0]['finish_reason']='length'
        raw['authorization']='Bearer '+self.fake_key
        raw['request']={'prompt':'private request must not be copied'}
        raw['usage']['echoed_header']=self.fake_key
        self.fetch.return_value=raw
        with self.assertRaises(api.RemoteError):
            self.vision().query('bounded diagnostics',max_tokens=130,schema=SCHEMA)
        files=list((self.responses/'rejected').glob('*.json'))
        self.assertEqual(len(files),1)
        diagnostic=json.loads(files[0].read_text('utf-8'))
        self.assertEqual(set(diagnostic),{'content','finish_reason','rejection_category','usage'})
        self.assertLessEqual(len(diagnostic['content']),20000)
        self.assertEqual(diagnostic['finish_reason'],'length')
        self.assertEqual(diagnostic['rejection_category'],'malformed_json')
        self.assertEqual(diagnostic['usage'],{'prompt_tokens':100,'completion_tokens':130})
        self.assertNotIn(self.fake_key,files[0].read_text('utf-8'))
        self.assertNotIn('private request must not be copied',files[0].read_text('utf-8'))
        self.assertTrue(files[0].resolve().is_relative_to(self.directory.resolve()))
        self.assertTrue(json.loads(self.ledger.read_text('utf-8'))['halted'])
        self.assertEqual(self.entries()[0]['status'],'completed')
        self.assertFalse(list(self.responses.glob('*.json')))

    def test_rejection_diagnostic_categories_are_strict_and_do_not_copy_raw_response(self):
        cases=[(reply('{"keep":["invented"]}'),'schema_rejection'),
               (reply('[]'),'non_object_json'),
               ({'usage':reply()['usage']},'response_shape')]
        for index,(raw,category) in enumerate(cases):
            with self.subTest(category=category):
                self.reset_fake_ledger()
                if raw.get('choices'):
                    raw['choices'][0]['finish_reason']=self.fake_key
                self.fetch.return_value=raw
                with self.assertRaises(api.RemoteError):
                    self.vision().query('category '+str(index),max_tokens=20,schema=SCHEMA)
                digest=self.entries()[-1]['request']
                diagnostic=json.loads((self.responses/'rejected'/(digest+'.json')).read_text('utf-8'))
                self.assertEqual(diagnostic['rejection_category'],category)
                self.assertIsNone(diagnostic['finish_reason'])
                self.assertNotIn(self.fake_key,json.dumps(diagnostic))

    def test_diagnostic_is_recorded_before_halt_and_io_failure_does_not_release_guard(self):
        self.fetch.return_value=reply('{"keep":["invented"]}')
        record=api._record_rejection
        def checked(*args):
            ledger=json.loads(self.ledger.read_text('utf-8'))
            self.assertEqual(ledger['entries'][-1]['status'],'completed')
            self.assertFalse(ledger.get('halted',False))
            return record(*args)
        atomic=api.atomic_json
        def fail_diagnostic(path,data):
            if path.parent.name=='rejected':
                raise OSError('simulated diagnostic disk failure')
            return atomic(path,data)
        with patch.object(api,'_record_rejection',side_effect=checked), \
                patch.object(api,'atomic_json',side_effect=fail_diagnostic), \
                self.assertLogs('app.deepseek',level='WARNING'):
            with self.assertRaises(api.RemoteError):
                self.vision().query('diagnostic failure',max_tokens=20,schema=SCHEMA)
        self.assertTrue(json.loads(self.ledger.read_text('utf-8'))['halted'])
        self.assertEqual(self.entries()[0]['status'],'completed')
        self.fetch.reset_mock()
        self.http.reset_mock()
        with self.assertRaises(api.BudgetExceeded):
            self.vision().query('next request',max_tokens=20,schema=SCHEMA)
        self.fetch.assert_not_called()
        self.http.assert_not_called()

    def test_unvalidated_usage_never_generates_rejected_response_diagnostics(self):
        self.fetch.return_value={**reply('not JSON'),'usage':{'prompt_tokens':True,'completion_tokens':130}}
        with self.assertRaises(api.RemoteError):
            self.vision().query('unknown usage diagnostic',max_tokens=130,schema=SCHEMA)
        self.assertFalse((self.responses/'rejected').exists())
        self.assertEqual(self.entries()[0]['status'],'unknown_usage')

    def test_explicit_recovery_cannot_release_unknown_billing_or_exceeded_reservation(self):
        self.fetch.side_effect = api.RemoteError('unknown billing')
        with self.assertRaises(api.RemoteError):
            self.vision().query('unknown', max_tokens=20, schema=SCHEMA)
        calls = self.http.call_count
        with self.assertRaises(api.RemoteError):
            api.resume_confirmed_requests()
        self.assertEqual(self.http.call_count, calls)
        self.assertTrue(json.loads(self.ledger.read_text('utf-8'))['halted'])
        ledger = json.loads(self.ledger.read_text('utf-8'))
        entry = ledger['entries'][0]
        entry.update(status='completed', usage={'prompt_tokens':1000000,'completion_tokens':0},
                     charged_ceiling_usd='0.3')
        self.ledger.write_text(json.dumps(ledger), encoding='utf-8')
        with self.assertRaises(api.RemoteError):
            api.resume_confirmed_requests()
        self.assertEqual(self.http.call_count, calls)

    def test_explicit_recovery_requires_verified_available_funds(self):
        self.fetch.return_value = reply('{"keep":["invented"]}')
        with self.assertRaises(api.RemoteError):
            self.vision().query('known bad', max_tokens=20, schema=SCHEMA)
        self.http.return_value = {'is_available':False,'balance_infos':[{'currency':'USD','total_balance':'0'}]}
        with self.assertRaises(api.RemoteError):
            api.resume_confirmed_requests()
        self.assertTrue(json.loads(self.ledger.read_text('utf-8'))['halted'])
