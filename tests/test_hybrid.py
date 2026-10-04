import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import uuid

from app.config import TEMP
from app.deepseek import BudgetExceeded, DeepSeekVision, RemoteError
from app.hybrid import HybridVision, query_checked, routing_profile


FOCUS = {'type':'object','properties':{'x':{'type':'number'},'y':{'type':'number'},
         'confidence':{'type':'number'},'visible_speaker':{'type':'boolean'}},
         'required':['x','y','confidence','visible_speaker'],'additionalProperties':False}
CLASSIFIER = {'type':'object','properties':{'contains_credits':{'type':'boolean'},
              'confidence':{'type':'number'},'uncertain':{'type':'boolean'}},
              'required':['contains_credits','confidence','uncertain'],'additionalProperties':False}
PARTITION = {'type':'object','properties':{
    'kept':{'type':'array','items':{'type':'string'}},
    'discarded':{'type':'array','items':{'type':'string'}},
    'confidence':{'type':'number'}},
    'required':['kept','discarded','confidence'],'additionalProperties':False}


def partition_valid(value):
    kept,discarded=value['kept'],value['discarded']
    if (len(kept)!=len(set(kept)) or len(discarded)!=len(set(discarded))
            or set(kept)&set(discarded) or set(kept)|set(discarded)!={'u000','u001'}):
        raise ValueError('Units must form an exact source partition')


def focus(confidence=.9, speaker=True, x=.3):
    return {'x':x,'y':.5,'confidence':confidence,'visible_speaker':speaker}


def classifier(confidence=.95, uncertain=False):
    return {'contains_credits':False,'confidence':confidence,'uncertain':uncertain}


class Local:
    def __init__(self, directory, response=None):
        self.model=directory/'fake-local.gguf'
        self.projector=directory/'fake-projector.gguf'
        self.thinking=False
        self.gpu_layers=7
        self.cpu_projector=False
        self.cpu_fallback=False
        self.query=Mock(return_value=focus() if response is None else response)
        self.token_count=Mock(return_value=123)
        self.entered=0
        self.closed=0

    def __enter__(self):
        self.entered+=1
        return self

    def __exit__(self,*args):
        self.close()

    def close(self):
        self.closed+=1


class RemoteProvider:
    """Simulated cloud cache separates paid requests from cache-only reads."""
    def __init__(self):
        self.answers=[]
        self.cache={}
        self.paid=[]
        self.cache_reads=[]
        self.instances=[]

    def key(self,prompt,image=None,max_tokens=1200,schema=None):
        pixels=image.read_bytes().hex() if image is not None else None
        return json.dumps([prompt,pixels,max_tokens,schema],sort_keys=True)

    def __call__(self,job_dir,cancelled,cache_only=False):
        provider=self
        class Client:
            def __init__(self):
                self.cache_only=cache_only
            def query(self,prompt,image=None,max_tokens=1200,schema=None):
                key=provider.key(prompt,image,max_tokens,schema)
                if self.cache_only:
                    provider.cache_reads.append(key)
                    if key not in provider.cache:
                        raise BudgetExceeded('Fake cache-only miss')
                    return copy.deepcopy(provider.cache[key])
                provider.paid.append(key)
                if not provider.answers:
                    raise AssertionError('Unexpected simulated paid request')
                answer=provider.answers.pop(0)
                if isinstance(answer,BaseException):
                    raise answer
                provider.cache[key]=copy.deepcopy(answer)
                return copy.deepcopy(answer)
            def __enter__(self):
                return self
            def __exit__(self,*args):
                self.close()
            def close(self):
                pass
        client=Client()
        self.instances.append(client)
        return client


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.directory=TEMP/('hybrid_'+uuid.uuid4().hex)
        self.directory.mkdir()
        self.provider=RemoteProvider()
        patcher=patch('app.hybrid.DeepSeekVision',side_effect=self.provider)
        patcher.start()
        self.addCleanup(patcher.stop)

    def vision(self,response=None,cancelled=lambda:False):
        local=Local(self.directory,response)
        return HybridVision(self.directory,cancelled,local),local

    def test_confident_schema_valid_but_semantically_invalid_local_routes_remote(self):
        wrong={'kept':['u000'],'discarded':['u000'],'confidence':.95}
        correct={'kept':['u000'],'discarded':['u001'],'confidence':.95}
        self.provider.answers=[correct]
        vision,local=self.vision(wrong)
        result=query_checked(vision,'partition validation',max_tokens=100,schema=PARTITION,
                             validator=partition_valid,validation_profile='domain-v1')
        self.assertEqual(result,correct)
        local.query.assert_called_once()
        self.assertEqual(len(self.provider.paid),1)

    def test_semantically_invalid_remote_keeps_valid_local_and_never_repeats_after_restart(self):
        valid={'kept':['u000'],'discarded':['u001'],'confidence':.8}
        wrong={'kept':['u000'],'discarded':['u000'],'confidence':.95}
        self.provider.answers=[wrong]
        for _ in range(2):
            vision,_=self.vision(valid)
            self.assertEqual(vision.query('invalid remote partition',schema=PARTITION,max_tokens=100,
                validator=partition_valid,validation_profile='domain-v1'),valid)
        self.assertEqual(len(self.provider.paid),1)

    def test_both_semantically_invalid_preserve_original_local_error_without_paid_retry(self):
        wrong={'kept':['u000'],'discarded':['u000'],'confidence':.95}
        original=ValueError('Original partition failure')
        def validate(value):
            try:
                partition_valid(value)
            except ValueError:
                raise original
        self.provider.answers=[wrong]
        for _ in range(2):
            vision,_=self.vision(wrong)
            with self.assertRaises(ValueError) as caught:
                query_checked(vision,'both invalid partitions',max_tokens=100,schema=PARTITION,
                              validator=validate,validation_profile='domain-v1')
            self.assertIs(caught.exception,original)
        self.assertEqual(len(self.provider.paid),1)

    def test_domain_validation_profile_changes_journal_digest(self):
        valid={'kept':['u000'],'discarded':['u001'],'confidence':.8}
        remote={**valid,'confidence':.95}
        self.provider.answers=[remote,remote]
        for profile in ['domain-v1','domain-v2']:
            vision,_=self.vision(valid)
            self.assertEqual(vision.query('same partition request',schema=PARTITION,max_tokens=100,
                validator=partition_valid,validation_profile=profile),remote)
        entries=json.loads((self.directory/'hybrid-reviews.json').read_text('utf-8'))['entries']
        self.assertEqual(len(entries),2)
        self.assertEqual(len(self.provider.paid),2)

    def test_query_checked_plain_local_and_remote_apply_domain_validation_once(self):
        valid={'kept':['u000'],'discarded':['u001'],'confidence':.95}
        wrong={'kept':['u000'],'discarded':['u000'],'confidence':.95}
        local=Local(self.directory,valid)
        checked=Mock(side_effect=partition_valid)
        self.assertEqual(query_checked(local,'local valid',max_tokens=100,schema=PARTITION,
            validator=checked,validation_profile='domain-v1'),valid)
        checked.assert_called_once_with(valid)
        # Bypass constructor so no real settings, balance or network are read.
        remote=object.__new__(DeepSeekVision)
        remote.query=Mock(return_value=wrong)
        with patch('app.hybrid.DeepSeekVision',DeepSeekVision):
            with self.assertRaises(RemoteError):
                query_checked(remote,'remote invalid',max_tokens=100,schema=PARTITION,
                    validator=partition_valid,validation_profile='domain-v1')
            local.query.return_value=wrong
            with self.assertRaisesRegex(ValueError,'exact source partition'):
                query_checked(local,'local invalid',max_tokens=100,schema=PARTITION,
                    validator=partition_valid,validation_profile='domain-v1')
        remote.query.assert_called_once()
        self.assertFalse(self.provider.paid)

    def test_confident_local_focus_and_classifier_make_no_cloud_request(self):
        for schema,response in ((FOCUS,focus(.75)),(CLASSIFIER,classifier(.85))):
            with self.subTest(schema=schema):
                vision,local=self.vision(response)
                result=vision.query('Current image',schema=schema,max_tokens=100)
                self.assertEqual(result,response)
                local.query.assert_called_once()
        self.assertFalse(self.provider.paid)

    def test_low_confidence_and_uncertain_local_are_reviewed(self):
        cases=[(FOCUS,focus(.7),focus(.6)),(CLASSIFIER,classifier(.84),classifier(.9)),
               (CLASSIFIER,classifier(.99,True),classifier(.95))]
        for index,(schema,local_result,remote_result) in enumerate(cases):
            with self.subTest(index=index):
                self.provider.answers.append(remote_result)
                vision,local=self.vision(local_result)
                result=vision.query('uncertain '+str(index),schema=schema,max_tokens=100)
                self.assertEqual(result,remote_result)
                local.query.assert_called_once()
        self.assertEqual(len(self.provider.paid),3)

    def test_visible_listener_with_phrase_is_uncertain_but_silent_action_is_not(self):
        local_result=focus(.99,False)
        vision,_=self.vision(local_result)
        self.assertEqual(vision.query('Locate main silent action',schema=FOCUS,max_tokens=100),local_result)
        self.assertFalse(self.provider.paid)
        self.provider.answers.append(focus(.9,True,.65))
        self.assertEqual(vision.query('Current phrase (evidence): Привет.',schema=FOCUS,max_tokens=100),focus(.9,True,.65))
        self.assertEqual(len(self.provider.paid),1)

    def test_local_invalid_schema_and_value_error_route_to_valid_remote(self):
        self.provider.answers=[focus(.9),focus(.8)]
        vision,_=self.vision({'confidence':.99})
        self.assertEqual(vision.query('invalid fields',schema=FOCUS,max_tokens=100),focus(.9))
        vision,local=self.vision()
        local.query.side_effect=ValueError('local malformed JSON')
        self.assertEqual(vision.query('local parse error',schema=FOCUS,max_tokens=100),focus(.8))
        self.assertEqual(len(self.provider.paid),2)

    def test_rejected_remote_preserves_valid_local_and_is_not_paid_again_after_restart(self):
        local_result=focus(.7)
        self.provider.answers=[focus(.5)]
        first,_=self.vision(local_result)
        self.assertEqual(first.query('weak remote',schema=FOCUS,max_tokens=100),local_result)
        restarted,_=self.vision(local_result)
        self.assertEqual(restarted.query('weak remote',schema=FOCUS,max_tokens=100),local_result)
        self.assertEqual(len(self.provider.paid),1)
        self.assertTrue((self.directory/'hybrid-reviews.json').is_file())

    def test_reviewed_answer_is_reused_after_restart_without_paid_request(self):
        remote=focus(.9,True,.75)
        self.provider.answers=[remote]
        first,_=self.vision(focus(.6))
        self.assertEqual(first.query('reviewed',schema=FOCUS,max_tokens=100),remote)
        restarted,local=self.vision(focus(.6))
        self.assertEqual(restarted.query('reviewed',schema=FOCUS,max_tokens=100),remote)
        local.query.assert_called_once()
        self.assertEqual(len(self.provider.paid),1)

    def test_budget_remote_and_io_failure_keep_local_and_disable_further_paid_requests(self):
        for index,error in enumerate((BudgetExceeded('fake cap'),RemoteError('fake network'),OSError('fake IO'))):
            with self.subTest(error=type(error).__name__):
                job=self.directory/str(index)
                job.mkdir()
                local=Local(job,focus(.6))
                self.provider.answers.append(error)
                before=len(self.provider.paid)
                first=HybridVision(job,lambda:False,local)
                self.assertEqual(first.query('unavailable '+str(index),schema=FOCUS,max_tokens=100),focus(.6))
                restarted=HybridVision(job,lambda:False,Local(job,focus(.6)))
                self.assertEqual(restarted.query('new question '+str(index),schema=FOCUS,max_tokens=100),focus(.6))
                self.assertEqual(len(self.provider.paid),before+1)

    def test_disabled_cloud_can_read_exact_cached_remote_without_payment(self):
        self.provider.cache[self.provider.key('already cached',None,100,FOCUS)]=focus(.9,True,.8)
        self.provider.answers=[BudgetExceeded('fake cap')]
        first,_=self.vision(focus(.6))
        first.query('disable cloud',schema=FOCUS,max_tokens=100)
        restarted,_=self.vision(focus(.6))
        result=restarted.query('already cached',schema=FOCUS,max_tokens=100)
        self.assertEqual(result,focus(.9,True,.8))
        self.assertEqual(len(self.provider.paid),1)
        self.assertTrue(self.provider.cache_reads)

    def test_invalid_local_and_unavailable_remote_raise_original_local_error(self):
        original=ValueError('original local response failed')
        self.provider.answers=[RemoteError('fake remote failure')]
        vision,local=self.vision()
        local.query.side_effect=original
        with self.assertRaises(ValueError) as caught:
            vision.query('both unavailable',schema=FOCUS,max_tokens=100)
        self.assertIs(caught.exception,original)
        self.assertEqual(len(self.provider.paid),1)

    def test_unresolved_journal_prevents_paid_retry_after_session_restart(self):
        self.provider.answers=[{'invented':'wrong schema'}]
        first,_=self.vision({'missing':'focus'})
        with self.assertRaises(ValueError):
            first.query('unresolved',schema=FOCUS,max_tokens=100)
        restarted,_=self.vision({'missing':'focus'})
        with self.assertRaises(ValueError):
            restarted.query('unresolved',schema=FOCUS,max_tokens=100)
        self.assertEqual(len(self.provider.paid),1)

    def test_cancellation_before_local_and_inside_either_provider_always_propagates(self):
        vision,local=self.vision(cancelled=lambda:True)
        with self.assertRaises(InterruptedError):
            vision.query('cancelled before local',schema=FOCUS,max_tokens=100)
        local.query.assert_not_called()
        vision,local=self.vision()
        local.query.side_effect=InterruptedError('local cancellation')
        with self.assertRaises(InterruptedError):
            vision.query('local cancel',schema=FOCUS,max_tokens=100)
        self.assertFalse(self.provider.paid)
        self.provider.answers=[InterruptedError('remote cancellation')]
        vision,_=self.vision(focus(.6))
        with self.assertRaises(InterruptedError):
            vision.query('remote cancel',schema=FOCUS,max_tokens=100)
        self.assertEqual(len(self.provider.paid),1)
        # The journal was persisted before the unknown billed cancellation.
        # Restarting the same request must use local work, never pay again.
        restarted,_=self.vision(focus(.6))
        self.assertEqual(restarted.query('remote cancel',schema=FOCUS,max_tokens=100),focus(.6))
        self.assertEqual(len(self.provider.paid),1)

    def test_remote_focus_boundary_is_accepted_but_weak_or_uncertain_classifier_is_not(self):
        cases=[(FOCUS,focus(.7),focus(.55,True,.7),focus(.55,True,.7)),
               (CLASSIFIER,classifier(.8),{**classifier(.84),'contains_credits':True},classifier(.8)),
               (CLASSIFIER,classifier(.8),classifier(.99,True),classifier(.8))]
        for index,(schema,local_result,remote_result,expected) in enumerate(cases):
            with self.subTest(index=index):
                self.provider.answers.append(remote_result)
                vision,_=self.vision(local_result)
                self.assertEqual(vision.query('remote boundary '+str(index),schema=schema,max_tokens=100),expected)
        self.assertEqual(len(self.provider.paid),3)

    def test_journal_is_durable_before_remote_attempt(self):
        def factory(job_dir,cancelled,cache_only=False):
            journal=self.directory/'hybrid-reviews.json'
            self.assertTrue(journal.is_file())
            self.assertTrue(json.loads(journal.read_text('utf-8')))
            return self.provider(job_dir,cancelled,cache_only=cache_only)
        self.provider.answers=[focus(.9)]
        with patch('app.hybrid.DeepSeekVision',side_effect=factory):
            vision,_=self.vision(focus(.6))
            self.assertEqual(vision.query('prepaid journal',schema=FOCUS,max_tokens=100),focus(.9))
        self.assertEqual(len(self.provider.paid),1)

    def test_request_identity_covers_prompt_pixels_schema_tokens_model_and_routing(self):
        image=self.directory/'frame.jpg'
        image.write_bytes(b'pixels one')
        self.provider.answers=[focus(.9)]*7
        vision,local=self.vision(focus(.6))
        vision.query('identity',image,schema=FOCUS,max_tokens=100)
        vision.query('changed prompt',image,schema=FOCUS,max_tokens=100)
        image.write_bytes(b'pixels two')
        vision.query('identity',image,schema=FOCUS,max_tokens=100)
        changed={**FOCUS,'description':'Different source validation'}
        vision.query('identity',image,schema=changed,max_tokens=100)
        vision.query('identity',image,schema=FOCUS,max_tokens=110)
        local.model=self.directory/'different-model.gguf'
        vision.query('identity',image,schema=FOCUS,max_tokens=100)
        with patch('app.hybrid.routing_profile',return_value={'profile':'changed'}):
            changed_vision=HybridVision(self.directory,lambda:False,local)
            changed_vision.query('identity',image,schema=FOCUS,max_tokens=100)
        self.assertEqual(len(self.provider.paid),7)

    def test_local_model_attributes_token_count_and_context_lifetime_are_forwarded(self):
        vision,local=self.vision()
        for name in ('model','projector','thinking','gpu_layers','cpu_projector','cpu_fallback'):
            self.assertEqual(getattr(vision,name),getattr(local,name))
        self.assertEqual(vision.token_count('local tokenizer'),123)
        local.token_count.assert_called_once_with('local tokenizer')
        with vision as active:
            self.assertIs(active,vision)
        self.assertEqual(local.entered,1)
        self.assertEqual(local.closed,1)
        self.assertFalse(self.provider.paid)

    def test_routing_profile_is_stable_serializable_without_network(self):
        self.assertEqual(routing_profile(),routing_profile())
        self.assertTrue(json.dumps(routing_profile(),sort_keys=True))
        self.assertFalse(self.provider.paid)

    def test_framing_checkpoint_invalidates_local_profile_then_reuses_identical_hybrid(self):
        from app.framing import refine_focus
        from tests.test_framing import FakeReader, fixtures
        source=self.directory/'исходная серия.mp4'
        source.write_bytes(b'fake source frames decoded only by FakeReader')
        events,shots,transcript=fixtures()
        local=Local(self.directory,focus(.95))
        with patch('app.framing.MAX_SAMPLE_INTERVAL',1000), patch('app.framing._FrameReader',side_effect=FakeReader):
            baseline=refine_focus(source,{'fps':30},transcript,shots,events,self.directory,local,
                lambda *a:None,lambda:False)
            self.assertEqual(local.query.call_count,2)
            hybrid_local=Local(self.directory,focus(.95))
            hybrid=HybridVision(self.directory,lambda:False,hybrid_local)
            revised=refine_focus(source,{'fps':30},transcript,shots,events,self.directory,hybrid,
                lambda *a:None,lambda:False)
            self.assertEqual(hybrid_local.query.call_count,2)
            restarted_local=Local(self.directory,focus(.95))
            restarted=HybridVision(self.directory,lambda:False,restarted_local)
            repeated=refine_focus(source,{'fps':30},transcript,shots,events,self.directory,restarted,
                lambda *a:None,lambda:False)
            restarted_local.query.assert_not_called()
        self.assertEqual(baseline,revised)
        self.assertEqual(revised,repeated)
        self.assertFalse(self.provider.paid)

    def test_analysis_review_warning_is_preserved_in_final_plan(self):
        from app.planner import build_plan
        from tests.test_planner import analysis
        data=analysis(20)
        data['warnings']=['Cloud budget unavailable; local analysis preserved']
        self.assertIn(data['warnings'][0],build_plan(data)['warnings'])
