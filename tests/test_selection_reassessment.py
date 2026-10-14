"""Explicit missing-view reassessment never restarts accepted evidence or paid rounds."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from app.analysis_continuation import attach_replies
from app.json_store import analysis_json as atomic_json
from app.selection_adjudication import adjudicate_event,_views
from app.selection_adjudication import _prior_native_view
from app.json_store import load_json
from tests import test_selection_adjudication as fixtures
from tests.test_selection_adjudication import FakeVision,answer,EMPTY


class ReassessmentTests(unittest.TestCase):
    setUp=fixtures.SelectionAdjudicationTests.setUp
    tearDown=fixtures.SelectionAdjudicationTests.tearDown
    board=fixtures.SelectionAdjudicationTests.board

    def initial(self,confidence=.7):
        def response(payload):
            missing=any(u['id']=='c000_u001' for u in payload['CURRENT']['units'])
            return answer(payload,selection_confidence=confidence if missing else .95)
        provider=FakeVision(response)
        result=adjudicate_event(self.source,self.event,EMPTY,[],self.job,provider,lambda:False)
        self.assertEqual(len(provider.requests),3)
        return result

    def retry(self,event,provider):
        return adjudicate_event(self.source,event,EMPTY,[],self.job,provider,lambda:False,
                                questions=['Уточни спорный CURRENT'],retry_unresolved=True)

    def test_only_failed_current_view_is_sent_and_accepted_views_keep_original_proof(self):
        prior=self.initial();old=copy.deepcopy(prior);provider=FakeVision()
        result=self.retry(prior,provider)
        self.assertEqual(len(provider.requests),1)
        self.assertEqual([u['id'] for u in provider.requests[0][3]['CURRENT']['units']],['c000_u001'])
        self.assertNotIn('HYPOTHESES',provider.requests[0][3])
        self.assertEqual(result['selection_status'],'accepted')
        before=old['selection_adjudication']['decisions'];after=result['selection_adjudication']['decisions']
        for index in (0,2):self.assertEqual(before[index]['checkpoint'],after[index]['checkpoint'])
        self.assertEqual(prior,old)
        warm=FakeVision(AssertionError('Accepted work must not be sent'))
        self.assertEqual(self.retry(result,warm)['selection_status'],'accepted')
        self.assertEqual(warm.requests,[])

    def test_worse_negative_answer_keeps_better_original_without_confidence_inflation(self):
        prior=self.initial(.8)
        provider=FakeVision(lambda p:answer(p,selection_confidence=.6))
        result=self.retry(prior,provider)
        self.assertEqual(len(provider.requests),1)
        self.assertEqual(result['selection_status'],'unresolved')
        self.assertEqual(result['selection_adjudication']['decisions'][1]['decision']['selection_confidence'],.8)
        warm=FakeVision(AssertionError('No second additional round'))
        self.assertEqual(self.retry(result,warm)['selection_status'],'unresolved')
        self.assertEqual(warm.requests,[])

    def test_invalid_answer_is_consumed_and_cannot_replace_original(self):
        result=self.retry(self.initial(),FakeVision({'unsupported':'bad contract'}))
        self.assertEqual(result['selection_status'],'unresolved')
        warm=FakeVision(AssertionError('Invalid reply cannot reopen the allowance'))
        self.retry(result,warm)
        self.assertEqual(warm.requests,[])

    def test_unknown_transport_outcome_is_not_sent_again(self):
        prior=self.initial()
        first=FakeVision(OSError('Response unavailable after dispatch'))
        result=self.retry(prior,first)
        self.assertEqual(len(first.requests),1)
        last=prior['selection_adjudication']['decisions'][2]['checkpoint']
        self.assertIn(last,[v['checkpoint'] for v in result['selection_adjudication']['prior_views']])
        warm=FakeVision(AssertionError('Unknown-charge request cannot be duplicated'))
        self.retry(result,warm)
        self.assertEqual(warm.requests,[])

    def test_provider_switch_and_same_byte_source_touch_do_not_buy_another_round(self):
        import os
        prior=self.initial(.8)
        result=self.retry(prior,FakeVision(lambda p:answer(p,selection_confidence=.6)))
        stat=self.source.stat();os.utime(self.source,ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000000))
        warm=FakeVision(AssertionError('Same source hash and cloud choice retain the allowance'))
        warm.model='other-cloud-model';warm.cache_profile={'provider':'antigravity_manual'}
        self.retry(result,warm)
        self.assertEqual(warm.requests,[])

    def test_exact_reply_bank_survives_implementation_change_without_new_queries(self):
        atomic_json(self.job/'analysis.meta.json',{'source':'a'*64,'version':16})
        first=FakeVision();attach_replies(first,self.job,'deepseek_plan',lambda:False)
        adjudicate_event(self.source,self.event,EMPTY,[],self.job,first,lambda:False)
        self.assertEqual(len(first.requests),3)
        warm=FakeVision(AssertionError('Exact accepted reply already exists'))
        attach_replies(warm,self.job,'antigravity_manual',lambda:False)
        original=Path.read_text
        def changed(path,*args,**kwargs):
            text=original(path,*args,**kwargs)
            return text+'\n# changed implementation\n' if path.name=='selection_adjudication.py' else text
        with patch.object(Path,'read_text',changed):
            result=adjudicate_event(self.source,self.event,EMPTY,[],self.job,warm,lambda:False,retry_unresolved=True)
        self.assertEqual(result['selection_status'],'accepted')
        self.assertEqual(warm.requests,[])

    def test_video_origin_within_one_frame_preserves_original_word_and_unit(self):
        with patch('app.selection_adjudication.inspect_media',return_value={'streams':[
            {'codec_type':'video','start_time':'.02','duration':'12','avg_frame_rate':'24/1'}]}):
            result=adjudicate_event(self.source,self.event,EMPTY,[],self.job,FakeVision(),lambda:False)
        self.assertEqual(result['selection_status'],'accepted')
        self.assertEqual(result['units'][0]['start'],0.)

    def test_original_checkpoint_keeps_original_storyboard_after_code_change(self):
        prior=self.initial();original=Path.read_text
        def changed(path,*args,**kwargs):
            text=original(path,*args,**kwargs)
            return text+'\n# presentation code changed\n' if path.name=='selection_adjudication.py' else text
        with patch.object(Path,'read_text',changed):
            result=self.retry(prior,FakeVision())
            self.assertEqual(result['selection_status'],'accepted')
            warm=FakeVision(AssertionError('Original proof mapping must survive a second warm resume'))
            self.retry(result,warm)
            self.assertEqual(warm.requests,[])

    def test_old_native_view_cannot_substitute_changed_current_pixels(self):
        prior=self.initial();audit=prior['selection_adjudication'];row=audit['decisions'][0]
        directory=self.job/'selection-adjudication'
        native=load_json(directory/(row['checkpoint']+'.json'));current=native['source_evidence']['CURRENT']
        found=_prior_native_view(prior,audit['source'],current['units'],current['frames'],directory,[],EMPTY,[],
                                 {'changed-current.jpg':'0'*64})
        self.assertIsNone(found)

    def test_large_unexplained_video_offset_is_still_rejected_without_dispatch(self):
        provider=FakeVision()
        with patch('app.selection_adjudication.inspect_media',return_value={'streams':[
            {'codec_type':'video','start_time':'3','duration':'12','avg_frame_rate':'24/1'}]}):
            result=adjudicate_event(self.source,self.event,EMPTY,[],self.job,provider,lambda:False)
        self.assertEqual(result['selection_status'],'unresolved')
        self.assertEqual(provider.requests,[])


def test_indivisible_word_uses_one_physical_page_without_changing_normal_views():
    unit={'id':'u','start':0.,'end':5.12}
    transcript={'words':[{'start':0.,'end':5.12,'text':'A whole original word'}]}
    views=_views([unit],transcript,[],lambda:False)
    assert [(v['start'],v['end']) for v in views]==[(0.,5.12)]
    with unittest.TestCase().assertRaises(ValueError):
        _views([{'id':'u','start':0.,'end':12.}],{'words':[{'start':0.,'end':12.,'text':'long'}]},[],lambda:False)
