import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.analysis import apply_global_selection
from app.closing import refine_closing_novelty
from app.config import TEMP
from app.editorial import DEFAULT_PROFILE
from app.planner import build_plan
from app.source_roles import (apply_exclusions, confirmed_exclusions, refine_source_roles,
                              validate_role_decisions)
from app.story import preserve_dialogue_in_credits, refine_story
from tests.test_story import FakeVision, edge_fixture


def role_answer(role, *, quote='', visible='', reaction=False, meaningful=False):
    return {'decisions':[{'unit':'A','role':role,'wholly_nonstory':role in ('uploader','next_preview','title_narration'),
                          'meaningful_story':meaningful,'reaction_or_humor':reaction,
                          'confidence':.98,'evidence':'Directly checked against the supplied scene context.',
                          'speech_quote':quote,'visible_text':visible}]}


def word_rows(start, end, text):
    words=text.split()
    width=(end-start)/len(words)
    return [{'start':start+i*width,'end':start+(i+1)*width,'text':word,'probability':.98}
            for i,word in enumerate(words)]


class SourceRolePipelineTests(unittest.TestCase):
    def test_legacy_opening_proof_stays_valid_but_pure_ending_needs_new_verified_ownership(self):
        from app.source_roles import confirmed_exclusions
        from app.production_sequence import VERSION
        proof={'start':5,'end':20,'version':8,'kind':'opening','boundaries_verified':True,
               'anchors_verified':True,'confidence':.95,'checkpoint':'a'*64+'.json',
               'anchors':[{'unit':'U001','type':'theme_credit','visible_text':'Opening theme'}]}
        event={'start':0,'end':30,'confirmed_opening_ranges':[{'start':5,'end':20}],
               'confirmed_opening_proofs':[proof]}
        self.assertEqual(confirmed_exclusions(event),[{'start':5.,'end':20.}])
        self.assertEqual(confirmed_exclusions({**event,'confirmed_opening_proofs':[{**proof,'version':9}]}),
                         [{'start':5.,'end':20.}])
        with self.assertRaises(ValueError):
            confirmed_exclusions({**event,'confirmed_opening_proofs':[{**proof,'boundaries_verified':False}]})
        ending={'start':0,'end':30,'confirmed_nonstory_ending_ranges':[{'start':5,'end':20}],
                'confirmed_nonstory_ending_proofs':[{**proof,'version':VERSION,'kind':'ending','wholly_nonstory':True}]}
        self.assertEqual(confirmed_exclusions(ending),[{'start':5.,'end':20.}])
        prior_ending={**ending,'confirmed_nonstory_ending_proofs':[
            {**ending['confirmed_nonstory_ending_proofs'][0],'version':9}]}
        self.assertEqual(confirmed_exclusions(prior_ending),[{'start':5.,'end':20.}])
        with self.assertRaises(ValueError):
            confirmed_exclusions({**prior_ending,'confirmed_nonstory_ending_proofs':[
                {**prior_ending['confirmed_nonstory_ending_proofs'][0],'wholly_nonstory':False}]})
        for change in ({'version':8},{'wholly_nonstory':False},{'anchors_verified':False}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                confirmed_exclusions({**ending,'confirmed_nonstory_ending_proofs':[{**ending['confirmed_nonstory_ending_proofs'][0],**change}]})

    def test_bare_or_malformed_opening_authority_fails_closed(self):
        from app.source_roles import confirmed_exclusions
        from app.production_sequence import VERSION
        event={'start':0,'end':30,'confirmed_opening_ranges':[{'start':5,'end':20}]}
        with self.assertRaises(ValueError):confirmed_exclusions(event)
        proof={'start':5,'end':20,'version':VERSION,'kind':'opening','boundaries_verified':True,
               'anchors_verified':True,'confidence':.95,'checkpoint':'a'*64+'.json',
               'anchors':[{'unit':'U001','type':'theme_credit','visible_text':'Opening theme'}]}
        valid={**event,'confirmed_opening_proofs':[proof]}
        self.assertEqual(confirmed_exclusions(valid),[{'start':5.,'end':20.}])
        for change in ({'kind':'ending'},{'boundaries_verified':False},{'anchors_verified':False},
                       {'confidence':.84},{'confidence':float('nan')},{'start':-1},
                       {'end':31},{'end':19},{'checkpoint':'unreviewed'}, {'anchors':[]}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                confirmed_exclusions({**event,'confirmed_opening_proofs':[{**proof,**change}]})

    def test_readable_layout_has_separate_cache_and_keeps_exact_target_context_and_two_reviews(self):
        directory,event,_=edge_fixture(start=0,end=5)
        event.update(contains_credits=True,selected_ranges=[{'start':0,'end':5}])
        text='Tomorrow they will meet again'
        transcript={'segments':[{'start':0,'end':5,'text':text}], 'words':word_rows(0,5,text)}
        decisions=[role_answer('next_preview',quote=text,visible='次回予告') for _ in range(2)]
        def vision(paged,answers):
            result=FakeVision(answers)
            result.model=Path('test-model');result.projector=Path('test-profile')
            result.cache_profile='test';result.supports_image_pages=paged
            return result
        old=vision(False,copy.deepcopy(decisions))
        new=vision(True,copy.deepcopy(decisions))
        with patch('app.production.sequence_sheet',return_value=[directory/'page.jpg']) as sheet:
            legacy=refine_source_roles([event],transcript,[],directory,old,lambda *a:None,lambda:False)
            readable=refine_source_roles([event],transcript,[],directory,new,lambda *a:None,lambda:False)
            self.assertEqual(sheet.call_count,2)
            first,second=sheet.call_args_list
            self.assertEqual(first.args[1:3],second.args[1:3])
            self.assertEqual(first.kwargs,{'page_size':None,'readable':False})
            self.assertEqual(second.kwargs,{'page_size':8,'readable':True})
            replay=vision(True,[])
            cached=refine_source_roles([event],transcript,[],directory,replay,lambda *a:None,lambda:False)
            self.assertEqual(sheet.call_count,2)
        self.assertEqual(legacy[0]['selected_ranges'],readable[0]['selected_ranges'])
        self.assertEqual(cached,readable)
        self.assertEqual(len(new.calls),2)
        self.assertFalse(replay.calls)
        self.assertEqual(len(list((directory/'source_roles').glob('*.json'))),2)

    def test_story_proof_splits_broad_exclusions_and_nonstory_elsewhere_stays_excluded(self):
        event={'id':'mixed','start':0,'end':20,'kind':'opening','importance':1,
               'selected_ranges':[{'start':0,'end':20}],
               'excluded_credit_ranges':[{'start':0,'end':20}],
               'verified_current_story_ranges':[{'start':8,'end':10}]}
        self.assertEqual(confirmed_exclusions(event),[
            {'start':0,'end':8.0},{'start':10.0,'end':20}])
        result=apply_exclusions([event])[0]
        self.assertEqual(result['selected_ranges'],[{'start':8.0,'end':10.0}])
        self.assertEqual(result['kind'],'story')

    def test_verified_story_range_survives_credit_exclusion_and_role_override(self):
        event={'id':'mixed','start':0,'end':20,'kind':'opening','importance':1,
               'credit_montage':True,'selected_ranges':[{'start':0,'end':20}],
               'excluded_credit_ranges':[{'start':0,'end':20}],
               'verified_current_story_ranges':[{'start':6,'end':12}],
               'source_role_excluded':True}
        restored=apply_exclusions([event])[0]
        self.assertEqual(restored['selected_ranges'],[{'start':6.0,'end':12.0}])
        self.assertEqual(restored['kind'],'story')
        self.assertNotIn('source_role_excluded',restored)
        unit={'id':'A','start':6,'end':12,'text':'Subscribe to the official channel',
              'verified_current_story':True}
        claim=role_answer('uploader',quote=unit['text'],visible='OFFICIAL CHANNEL')
        self.assertEqual(validate_role_decisions(claim,[unit]),[])
        preview=role_answer('next_preview',quote='Tomorrow the next episode begins',visible='次回予告')
        self.assertEqual(validate_role_decisions(preview,[{**unit,'text':'Tomorrow the next episode begins'}]),[])

    def test_explicit_preview_marker_can_override_atmosphere_label_but_story_reaction_cannot(self):
        units=[{'id':'A','text':'','protected_atmosphere':True},
               {'id':'B','text':'Character laughs at the current story','protected_atmosphere':True}]
        raw={'decisions':[
            {'unit':'A','role':'next_preview','wholly_nonstory':True,'meaningful_story':False,
             'reaction_or_humor':False,'confidence':.98,'evidence':'Visible next-episode card follows the episode ending.',
             'speech_quote':'','visible_text':'次回予告'},
            {'unit':'B','role':'current_story','wholly_nonstory':False,'meaningful_story':False,
             'reaction_or_humor':True,'confidence':.98,'evidence':'Character reaction belongs to this scene.',
             'speech_quote':'Character laughs','visible_text':''}]}
        self.assertEqual([d['unit'] for d in validate_role_decisions(raw,units)],['A'])

    def test_protected_preview_without_visible_marker_stays_and_malformed_claim_fails_closed(self):
        unit={'id':'A','text':'Tomorrow they will meet again','protected_atmosphere':True}
        plain_quote={'decisions':[{'unit':'A','role':'next_preview','wholly_nonstory':True,
            'meaningful_story':False,'reaction_or_humor':False,'confidence':.98,
            'evidence':'The wording sounds like a preview.','speech_quote':'Tomorrow they will meet again',
            'visible_text':''}]}
        self.assertEqual(validate_role_decisions(plain_quote,[unit]),[])
        malformed={'decisions':[dict(plain_quote['decisions'][0],visible_text=None)]}
        with self.assertRaises(ValueError):
            validate_role_decisions(malformed,[unit])

    def test_protected_uploader_and_title_need_matching_quote_and_visible_marker(self):
        for role,text,marker in [('uploader','Subscribe to our official channel','OFFICIAL CHANNEL'),
                                 ('title_narration','This episode is called Marie','EPISODE 1')]:
            with self.subTest(role=role):
                unit={'id':'A','text':text,'protected_atmosphere':True}
                confirmed=role_answer(role,quote=text,visible=marker)
                self.assertEqual(len(validate_role_decisions(confirmed,[unit])),1)
                unsupported=role_answer(role,quote=text,visible='')
                self.assertEqual(validate_role_decisions(unsupported,[unit]),[])

    def test_production_credit_requires_typed_visible_marker_and_sequence_context(self):
        unit={'id':'A','start':10,'end':12,'text':'','production_sequence_context':True}
        base={'unit':'A','role':'production_credit','wholly_nonstory':True,
              'meaningful_story':False,'reaction_or_humor':False,'confidence':.97,
              'evidence':'Visible staff card follows the independently confirmed opening sequence.',
              'speech_quote':'','visible_text':'Animation staff','marker_type':'staff_credit',
              'same_production_sequence':True}
        self.assertEqual([row['unit'] for row in validate_role_decisions({'decisions':[base]},[unit])],['A'])
        for changes in ({'production_sequence_context':False}, {'verified_current_story':True}):
            kept={**unit,**changes}
            self.assertEqual(validate_role_decisions({'decisions':[base]},[kept]),[])
        for changes in ({'marker_type':'none'}, {'same_production_sequence':False},
                        {'meaningful_story':True}, {'reaction_or_humor':True},
                        {'confidence':.89}, {'visible_text':''}):
            answer={**base,**changes}
            self.assertEqual(validate_role_decisions({'decisions':[answer]},[unit]),[])

    def test_production_credit_speech_must_match_the_unit_quote(self):
        unit={'id':'A','text':'Staff names scroll across the screen',
              'production_sequence_context':True}
        answer={'unit':'A','role':'production_credit','wholly_nonstory':True,
                'meaningful_story':False,'reaction_or_humor':False,'confidence':.97,
                'evidence':'Visible staff roll in the confirmed sequence.',
                'speech_quote':'An invented theme lyric','visible_text':'Animation staff',
                'marker_type':'staff_credit','same_production_sequence':True}
        self.assertEqual(validate_role_decisions({'decisions':[answer]},[unit]),[])

    def test_role_deletion_requires_complete_valid_evidence_and_positive_credit_span(self):
        units=[{'id':'A','text':'Official channel subscribes today'},
               {'id':'B','text':'Tomorrow another episode starts'},
               {'id':'C','text':'Narrator says the episode name'},
               {'id':'D','text':'Opening theme lyrics'}]
        rows=[
            {'unit':'A','role':'uploader','wholly_nonstory':True,'meaningful_story':False,
             'reaction_or_humor':False,'confidence':.99,'evidence':'No story context.',
             'speech_quote':'Official channel subscribes tomorrow','visible_text':''},
            {'unit':'B','role':'next_preview','wholly_nonstory':True,'meaningful_story':False,
             'reaction_or_humor':False,'confidence':.99,'evidence':'No story context.',
             'speech_quote':'','visible_text':''},
            {'unit':'C','role':'title_narration','wholly_nonstory':True,'meaningful_story':False,
             'reaction_or_humor':False,'confidence':.99,'evidence':'No story context.',
             'speech_quote':'Narrator says the episode name','visible_text':''},
            {'unit':'D','role':'song_or_artifact','wholly_nonstory':True,'meaningful_story':False,
             'reaction_or_humor':False,'confidence':.99,'evidence':'No story context.',
             'speech_quote':'','visible_text':''},
        ]
        self.assertEqual(validate_role_decisions({'decisions':rows},units,credit_confirmed=False),[])

        complete={'decisions':rows[:3]+[{**rows[3],'wholly_nonstory':'true'}]}
        with self.assertRaises(ValueError):
            validate_role_decisions(complete,units,credit_confirmed=True)
        duplicate={'decisions':rows[:3]+[{**rows[3],'unit':'C'}]}
        with self.assertRaises(ValueError):
            validate_role_decisions(duplicate,units,credit_confirmed=True)

    def test_role_exclusions_survive_speech_rescue_serialization_and_planning(self):
        directory, base, _=edge_fixture(start=0,end=50)
        texts=['Please subscribe to the official channel and follow us',
               'That was funny, I laughed again',
               '',
               'The current story continues at the workplace',
               'Next episode begins tomorrow, meet everyone']
        events=[]
        segments=[]
        words=[]
        for index,text in enumerate(texts):
            start,end=index*10,(index+1)*10
            event={**copy.deepcopy(base),'id':f'event_{index:04d}','start':start,'end':end,
                   'kind':'story','importance':4,'requires':[],
                   'selected_ranges':[{'start':start,'end':end}],
                   'contains_credits':True,'credit_montage':index==0}
            events.append(event)
            if text:
                segments.append({'start':start,'end':end,'text':text})
                words.extend(word_rows(start,end,text))
        transcript={'segments':segments,'words':words}

        # The first and last units are independently confirmed removable roles.
        # A reaction, consequential silent action, and real current-story line stay.
        vision=FakeVision([
            role_answer('uploader',quote=texts[0]), role_answer('uploader',quote=texts[0]),
            role_answer('current_story',reaction=True),
            role_answer('current_story',meaningful=True),
            role_answer('current_story'),
            role_answer('next_preview',quote=texts[4]), role_answer('next_preview',quote=texts[4]),
        ])
        vision.model=Path('test-model');vision.projector=Path('test-profile')
        vision.cache_profile='test';vision.supports_image_pages=False
        rescued=preserve_dialogue_in_credits(events,transcript)
        self.assertTrue(rescued[0]['credit_dialogue_rescued'])
        with patch('app.production.sequence_sheet',return_value=[directory/'role-page.jpg']):
            filtered=refine_source_roles(rescued,transcript,
                [{'start':i*10,'end':(i+1)*10} for i in range(5)],directory,
                vision,lambda *a:None,lambda:False)

        replay=FakeVision([])
        replay.model=vision.model;replay.projector=vision.projector
        replay.cache_profile=vision.cache_profile;replay.supports_image_pages=False
        with patch('app.production.sequence_sheet',return_value=[directory/'role-page.jpg']):
            cached=refine_source_roles(rescued,transcript,
                [{'start':i*10,'end':(i+1)*10} for i in range(5)],directory,
                replay,lambda *a:None,lambda:False)
        self.assertEqual(cached,filtered)
        self.assertFalse(replay.calls)

        # JSON persistence must retain all exclusion provenance before the
        # dialogue and planner guards run on a cached analysis result.
        loaded=json.loads(json.dumps(filtered))
        loaded=preserve_dialogue_in_credits(loaded,transcript)
        plan=build_plan({'probe':{'duration':50,'width':1920,'height':1080,'has_audio':True},
                         'events':loaded,'transcript':transcript,'shots':[]})
        cuts=[(c['start'],c['end']) for part in plan['parts'] for c in part['cuts']]
        self.assertEqual(cuts,[(10,40)])
        subtitles=' '.join(c['text'] for part in plan['parts'] for c in part['subtitles'])
        self.assertNotIn('subscribe',subtitles.lower())
        self.assertNotIn('Next episode',subtitles)
        self.assertIn('funny',subtitles)
        self.assertIn('current story',subtitles)
        self.assertTrue(loaded[0]['source_role_excluded'])
        self.assertEqual(loaded[1]['selected_ranges'],[{'start':10,'end':20}])
        self.assertEqual(loaded[2]['selected_ranges'],[{'start':20,'end':30}])

    def test_preview_marker_can_remove_tentatively_protected_unit_after_two_agreeing_reviews(self):
        directory,base,_=edge_fixture(start=0,end=20)
        event={**copy.deepcopy(base),'contains_credits':True,
               'protected_atmosphere_ranges':[{'start':0,'end':20}],
               'selected_ranges':[{'start':0,'end':20}]}
        text='Tomorrow the next episode begins'
        transcript={'segments':[{'start':2,'end':20,'text':text}],
                    'words':word_rows(2,20,text)}
        visible='次回予告'
        vision=FakeVision([role_answer('next_preview',quote=text,visible=visible),
                           role_answer('next_preview',quote=text,visible=visible)])
        vision.model=Path('test-model');vision.projector=Path('test-profile')
        vision.cache_profile='test';vision.supports_image_pages=False
        with patch('app.production.sequence_sheet',return_value=[directory/'preview-page.jpg']):
            result=refine_source_roles([event],transcript,[],directory,vision,lambda *a:None,lambda:False)
        self.assertFalse(result[0]['selected_ranges'])
        self.assertTrue(result[0]['source_role_excluded'])
        self.assertEqual(len(vision.calls),2)

    def test_disagreeing_preview_role_reviewer_preserves_protected_content(self):
        directory,event,_=edge_fixture(start=0,end=20)
        event.update(contains_credits=True,protected_atmosphere_ranges=[{'start':0,'end':20}],
                     selected_ranges=[{'start':0,'end':20}])
        text='Tomorrow the next episode begins'
        transcript={'segments':[{'start':2,'end':20,'text':text}], 'words':word_rows(2,20,text)}
        vision=FakeVision([role_answer('next_preview',quote=text,visible='次回予告'),
                           role_answer('current_story')])
        vision.model=Path('test-model');vision.projector=Path('test-profile')
        vision.cache_profile='test';vision.supports_image_pages=False
        with patch('app.production.sequence_sheet',return_value=[directory/'preview-page.jpg']):
            result=refine_source_roles([event],transcript,[],directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':20}])
        self.assertFalse(result[0].get('source_role_excluded',False))

    def test_closing_rechecks_and_keeps_concretely_proven_current_reaction(self):
        from tests.test_closing import decision as closing_decision
        from tests.test_story import decision as story_decision, fixture as story_fixture

        directory,event,_=edge_fixture(start=0,end=20,kind='ending')
        _,authored,transcript=story_fixture()
        event['units']=copy.deepcopy(authored[0]['units'])
        raw={**story_decision(['u001','u003']),
             'omit_units':[{'unit':'u000','reason':'waiting','reaction_or_humor':False},
                           {'unit':'u002','reason':'repeated_information','reaction_or_humor':False}]}
        proof={'decisions':[
            {'unit':'u000','keep':True,'story_change':False,'reaction_or_humor':True,
             'reaction_kind':'character_reaction','frame_indices':[1],
             'current_episode_story':True,'confidence':.98,'retained_witness':'none',
             'evidence':'The current character notices the reply, turns and responds in the same scene.'},
            {'unit':'u002','keep':False,'story_change':False,'reaction_or_humor':False,
             'current_episode_story':False,'confidence':.98,'retained_witness':'u001',
             'evidence':'The earlier retained reply conveys the same information without another reaction.'}]}
        story=refine_story([event],transcript,[],directory,FakeVision([raw,proof]),lambda *a:None,lambda:False)
        self.assertEqual(story[0]['verified_current_story_ranges'],[{'start':0,'end':6}])
        story[0].update(kind='ending',credits_kind='ending',credit_montage=True,
                        contains_credits=True,importance=1,
                        selected_ranges=[{'start':0,'end':20}])

        # A no-new-facts closing decision must not delete the reaction marked
        # by story refinement. The same exclusion proof survives role review,
        # speech-context reapplication, pacing review, and final planning.
        class ClosingVision:
            model='test';projector='test'
            def query(self,*args,**kwargs):
                return closing_decision(['u000'],[])
        closed=refine_closing_novelty(story,transcript,[],directory,ClosingVision(),
                                     lambda *a:None,lambda:False)
        self.assertEqual(closed[0]['selected_ranges'],[{'start':0,'end':20}])
        self.assertNotIn('excluded_closing_ranges',closed[0])

        class RoleVision:
            model=Path('test-model');projector=Path('test-profile')
            cache_profile='test';supports_image_pages=False
            def query(self,prompt,image,max_tokens,schema):
                ids=schema['properties']['decisions']['items']['properties']['unit']['enum']
                return {'decisions':[{'unit':uid,'role':'current_story','wholly_nonstory':False,
                    'meaningful_story':False,'reaction_or_humor':True,'confidence':.98,
                    'evidence':'The current scene carries character atmosphere.',
                    'speech_quote':'','visible_text':''} for uid in ids]}
        with patch('app.production.sequence_sheet',return_value=[directory/'source-role.jpg']):
            roles=refine_source_roles(closed,transcript,[],directory,RoleVision(),
                                      lambda *a:None,lambda:False)
        from app.speech_context import protect_speech_context
        speech=protect_speech_context(roles,transcript)
        from app.pacing import refine_pacing

        class PacingVision:
            model=Path('test-model');projector=Path('test-profile');cache_profile='test'
            def query(self,prompt,image,max_tokens,schema):
                ids=schema['properties']['decisions']['items']['properties']['unit']['enum']
                return {'uncertain':False,'decisions':[{'unit':uid,'keep':False,
                    'reason':'waiting','story_change':False,'reaction_or_humor':False,
                    'evidence':'No new plot fact in unchanged scenery.'} for uid in ids]}
        with patch('app.pacing.make_sheet'):
            paced=refine_pacing(directory/'episode.mkv',speech,transcript,[],directory,PacingVision(),
                lambda *a:None,lambda:False)
        self.assertFalse(paced[0].get('pacing_excluded'),json.dumps(paced[0],ensure_ascii=True))
        plan=build_plan({'probe':{'duration':20,'width':1920,'height':1080,'has_audio':True},
                         'events':paced,'transcript':transcript,'shots':[]})
        cuts=[(c['start'],c['end']) for part in plan['parts'] for c in part['cuts']]
        self.assertTrue(any(start<=0.01 and end>=5.99 for start,end in cuts))
        self.assertEqual(paced[0]['verified_current_story_ranges'],[{'start':0,'end':6}])

    def test_tentative_atmosphere_hint_does_not_overrule_reviewed_neutral_waiting(self):
        from app.pacing import apply_review
        event={'id':'one','start':0,'end':10,'kind':'story','importance':4,
               'selected_ranges':[{'start':0,'end':10}],
               'protected_atmosphere_units':['u000'],
               'protected_atmosphere_ranges':[{'start':0,'end':6}]}
        apply_review(event,[{'id':'A','start':0,'end':6}],{'uncertain':False,'decisions':[
            {'unit':'A','keep':False,'reason':'waiting','story_change':False,'reaction_or_humor':False,
             'evidence':'The same neutral pose remains unchanged; the retained next shot establishes the scene.'}]})
        self.assertEqual(event['selected_ranges'],[{'start':6,'end':10}])

    def test_global_review_and_empty_hold_settings_preserve_reaction_and_repetition(self):
        profile={**DEFAULT_PROFILE,'remove_exact_repetition':False,'remove_empty_holds':False}
        events=[{'id':'reaction','start':0,'end':10,'kind':'story','importance':1,'requires':[]},
                {'id':'plot','start':10,'end':20,'kind':'story','importance':4,'requires':[]}]
        apply_global_selection(events,{'keep':['plot'],'omit':[{'event':'reaction','reason':'nonstory',
            'evidence':'No new plot fact','confidence':.98,'reaction_or_humor':True}]},profile)
        self.assertNotIn('global_excluded',events[0])
