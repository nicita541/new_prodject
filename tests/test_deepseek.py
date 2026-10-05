"""Current provider contract replaces obsolete monetary gate tests."""
import hashlib
from pathlib import Path
import shutil
import uuid
import unittest
from unittest.mock import patch
from app import deepseek as api
from app.config import TEMP

SCHEMA={'type':'object','properties':{'keep':{'type':'array','items':{'type':'string','enum':['A']}}},'required':['keep'],'additionalProperties':False}
def response(text='{"keep":["A"]}'):
    return {'choices':[{'message':{'content':text}}]}

class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(exist_ok=True,parents=True)
        self.root=TEMP/('deepseek_test_'+uuid.uuid4().hex)
        self.root.mkdir()
        self.patches=[patch.object(api,'RESPONSES',self.root/'responses'),patch.object(api,'PRIVATE',self.root/'private.json'),patch.object(api,'_key',return_value='test-key'),patch.object(api.time,'sleep'),patch.object(api.time,'monotonic',side_effect=range(10000))]
        for p in self.patches:p.start()
        self.vision=api.DeepSeekVision(self.root,lambda:False)
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.root.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.root)
    def test_no_usage_required_and_cache_prevents_duplicate(self):
        with patch.object(self.vision,'_fetch',return_value=response()) as fetch:
            self.assertEqual(self.vision.query('current',schema=SCHEMA),{'keep':['A']})
            self.vision.query('current',schema=SCHEMA)
        self.assertEqual(fetch.call_count,1)
    def test_two_transport_retries_then_success(self):
        error=api.RemoteError('network',category='transport')
        with patch.object(self.vision,'_fetch',side_effect=[error,error,response()]) as fetch:
            self.vision.query('current',schema=SCHEMA)
        self.assertEqual(fetch.call_count,3)
    def test_exhaustion_does_not_disable_next_query(self):
        with patch.object(self.vision,'_fetch',side_effect=api.RemoteError('network',category='transport')) as fetch:
            with self.assertRaisesRegex(api.RemoteError,'3 попыток'):self.vision.query('current',schema=SCHEMA)
        self.assertEqual(fetch.call_count,3)
        with patch.object(self.vision,'_fetch',return_value=response()) as fetch:self.vision.query('current',schema=SCHEMA)
        fetch.assert_called_once()
    def test_schema_errors_retry_without_accepting_wrong_ids(self):
        with patch.object(self.vision,'_fetch',side_effect=[response('{"keep":["B"]}'),response('[]'),response()]) as fetch:
            self.assertEqual(self.vision.query('current',schema=SCHEMA),{'keep':['A']})
        self.assertEqual(fetch.call_count,3)
    def test_truncated_json_and_missing_choices_retry(self):
        with patch.object(self.vision,'_fetch',side_effect=[response('{'),{},response()]) as fetch:self.vision.query('current',schema=SCHEMA)
        self.assertEqual(fetch.call_count,3)
    def test_auth_and_certificate_errors_do_not_retry(self):
        for error in (api.RemoteError('auth',category='http',http_status=401),api.RemoteError('auth',category='http',http_status=403),api.RemoteError('tls',category='transport',cause_type='SSLCertVerificationError')):
            with self.subTest(error=error.category),patch.object(self.vision,'_fetch',side_effect=error) as fetch:
                with self.assertRaises(api.RemoteError):self.vision.query('current',schema=SCHEMA)
                fetch.assert_called_once()
    def test_cancel_before_and_between_attempts_stops_send(self):
        self.vision.cancelled=lambda:True
        with patch.object(self.vision,'_fetch') as fetch:
            with self.assertRaises(InterruptedError):self.vision.query('current',schema=SCHEMA)
            fetch.assert_not_called()
        self.vision.cancelled=lambda:False
        def fail(_):
            self.vision.cancelled=lambda:True
            raise api.RemoteError('network',category='transport')
        with patch.object(self.vision,'_fetch',side_effect=fail) as fetch:
            with self.assertRaises(InterruptedError):self.vision.query('current',schema=SCHEMA)
            fetch.assert_called_once()
    def test_cache_only_never_creates_cache_or_fetches(self):
        self.vision.cache_only=True
        with patch.object(self.vision,'_fetch') as fetch:
            with self.assertRaises(api.BudgetExceeded):self.vision.query('current',schema=SCHEMA)
            fetch.assert_not_called()
        self.assertFalse((self.root/'responses').exists())
    def test_halted_and_corrupt_legacy_ledger_are_ignored_unchanged(self):
        ledger=self.root/'deepseek-spending.json'
        for old in ('not json','{"halted":true,"entries":[{"status":"unknown"}]}'):
            with self.subTest(old=old):
                ledger.write_text(old);before=hashlib.sha256(ledger.read_bytes()).hexdigest()
                with patch.object(self.vision,'_fetch',return_value=response()):self.vision.query(old,schema=SCHEMA)
                self.assertTrue(api.public_status()['configured']);self.assertFalse(api.recovery_status()['halted'])
                api.begin_attempt(self.root)
                self.assertEqual(hashlib.sha256(ledger.read_bytes()).hexdigest(),before)
    def test_connection_check_uses_only_models(self):
        with patch.object(api,'_http',return_value={'data':[{'id':api.MODEL,'input_modalities':['image','text']}]}) as http:self.assertTrue(api.check_connection()['vision_supported'])
        http.assert_called_once_with('/models')
    def test_all_pages_are_sent_and_affect_cache(self):
        pages=[self.root/'one.jpg',self.root/'two.jpg']
        for p in pages:p.write_bytes(b'pixels')
        with patch.object(self.vision,'_fetch',return_value=response()) as fetch:
            self.vision.query('current',pages,schema=SCHEMA)
            self.assertEqual(len(fetch.call_args.args[0]['messages'][1]['content']),3)
            pages[1].write_bytes(b'changed');self.vision.query('current',pages,schema=SCHEMA)
        self.assertEqual(fetch.call_count,2)
    def test_invalid_page_count_and_nonfinite_json_are_rejected(self):
        with patch.object(self.vision,'_fetch') as fetch:
            for pages in ([],[self.root/'missing']*9):
                with self.assertRaises(ValueError):self.vision.query('current',pages,schema=SCHEMA)
            fetch.assert_not_called()
        for text in ('{"n":NaN}','{"n":Infinity}','{"n":1e999}'):
            with self.assertRaises(ValueError):api._strict_json(text)
    def test_final_error_does_not_leak_exception_or_key(self):
        with patch.object(self.vision,'_fetch',side_effect=api.RemoteError('Bearer secret-token',category='transport')):
            with self.assertRaises(api.RemoteError) as error:self.vision.query('current',schema=SCHEMA)
        self.assertNotIn('secret-token',str(error.exception))
    def test_http_server_error_retries(self):
        with patch.object(self.vision,'_fetch',side_effect=[api.RemoteError('server',category='http',http_status=503),response()]) as fetch:self.vision.query('current',schema=SCHEMA)
        self.assertEqual(fetch.call_count,2)

    def test_sharded_cache_lookup_and_write(self):
        with patch.object(self.vision, '_fetch', return_value=response()) as fetch:
            res = self.vision.query('sharded_test_query', schema=SCHEMA)
            self.assertEqual(res, {'keep': ['A']})
        # Check that it wrote to a 2-char subfolder inside responses
        resp_dir = self.root / 'responses'
        sharded_files = list(resp_dir.glob('*/*.json'))
        self.assertEqual(len(sharded_files), 1)
        subfolder = sharded_files[0].parent
        self.assertEqual(len(subfolder.name), 2)
        self.assertTrue(sharded_files[0].name.startswith(subfolder.name))

    def test_legacy_flat_cache_fallback(self):
        import json
        resp_dir = self.root / 'responses'
        resp_dir.mkdir(parents=True, exist_ok=True)
        # Mock fetch to return a unique response
        with patch.object(self.vision, '_fetch', return_value=response('{"keep":["A"]}')) as fetch:
            self.vision.query('legacy_query', schema=SCHEMA)
        # Find the sharded file created and move it to flat root
        sharded_file = list(resp_dir.glob('*/*.json'))[0]
        flat_file = resp_dir / sharded_file.name
        sharded_file.replace(flat_file)
        sharded_file.parent.rmdir()
        self.assertTrue(flat_file.is_file())

        # Second query should read from flat file without network fetch
        with patch.object(self.vision, '_fetch') as fetch:
            res = self.vision.query('legacy_query', schema=SCHEMA)
            self.assertEqual(res, {'keep': ['A']})
            fetch.assert_not_called()

    def test_migrate_flat_cache_moves_all_files(self):
        import json
        resp_dir = self.root / 'responses'
        resp_dir.mkdir(parents=True, exist_ok=True)
        hash1 = 'aabb11223344556677889900aabbccddeeff0011223344556677889900aabbcc'
        hash2 = 'ccdd11223344556677889900aabbccddeeff0011223344556677889900aabbcc'
        (resp_dir / f'{hash1}.json').write_text(json.dumps({'result': {'keep': ['A']}}), encoding='utf-8')
        (resp_dir / f'{hash2}.json').write_text(json.dumps({'result': {'keep': ['A']}}), encoding='utf-8')

        stats = api.cache_stats(resp_dir)
        self.assertEqual(stats['flat_files'], 2)
        self.assertEqual(stats['sharded_files'], 0)

        result = api.migrate_flat_cache(resp_dir)
        self.assertEqual(result['migrated'], 2)
        self.assertEqual(result['errors'], 0)

        stats_after = api.cache_stats(resp_dir)
        self.assertEqual(stats_after['flat_files'], 0)
        self.assertEqual(stats_after['sharded_files'], 2)
        self.assertTrue((resp_dir / 'aa' / f'{hash1}.json').is_file())
        self.assertTrue((resp_dir / 'cc' / f'{hash2}.json').is_file())

    def test_prune_cache_corrupted_and_limits(self):
        import json, time
        resp_dir = self.root / 'responses'
        resp_dir.mkdir(parents=True, exist_ok=True)
        # Create corrupted 0-byte file
        corrupt1 = resp_dir / '00' / '00zero.json'
        corrupt1.parent.mkdir(exist_ok=True)
        corrupt1.write_bytes(b'')

        # Create invalid json file
        corrupt2 = resp_dir / '11' / '11bad.json'
        corrupt2.parent.mkdir(exist_ok=True)
        corrupt2.write_bytes(b'not json')

        # Create valid entries
        valid1 = resp_dir / '22' / '22valid1.json'
        valid1.parent.mkdir(exist_ok=True)
        valid1.write_text(json.dumps({'result': {'keep': ['A']}}), encoding='utf-8')

        valid2 = resp_dir / '33' / '33valid2.json'
        valid2.parent.mkdir(exist_ok=True)
        valid2.write_text(json.dumps({'result': {'keep': ['A']}}), encoding='utf-8')

        # Test corrupt removal
        res = api.prune_cache(resp_dir, max_entries=10, remove_corrupted=True)
        self.assertEqual(res['corrupted_removed'], 2)
        self.assertEqual(res['remaining'], 2)
        self.assertFalse(corrupt1.exists())
        self.assertFalse(corrupt2.exists())
        self.assertTrue(valid1.exists())
        self.assertTrue(valid2.exists())

        # Test max_entries limit pruning
        res_limit = api.prune_cache(resp_dir, max_entries=1)
        self.assertEqual(res_limit['limit_pruned'], 1)
        self.assertEqual(res_limit['remaining'], 1)

