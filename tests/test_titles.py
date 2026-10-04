import copy
import json
import unittest
import uuid
from unittest.mock import patch

from PIL import Image

from app.config import TEMP
from app.titles import TITLES_VERSION, refine_titles


class Vision:
    def __init__(self, answers):
        self.answers=list(answers)
        self.calls=[]

    def query(self,prompt,image,max_tokens,schema):
        self.calls.append((prompt,image,max_tokens,schema))
        return self.answers.pop(0)


def decision(title=False, confidence=.95, narrative=False, dialogue=False, narrated=False):
    return {'visible_production_title':title,'wholly_nonnarrative':title,
            'continuous_narrative':narrative,'meaningful_character_dialogue':dialogue,
            'narrated_title':narrated,'confidence':confidence}


def frames(source,start,end,shots,transcript,destination,cancelled):
    Image.new('RGB',(48,27),(int(start),int(end),0)).save(destination)
    return [start,end]


def fixture():
    directory=TEMP/('titles_'+uuid.uuid4().hex)
    directory.mkdir()
    source=directory/'серия с пробелами.mkv'
    source.write_bytes(b'original')
    (directory/'source.json').write_text(json.dumps({'path':str(source)}),encoding='utf-8')
    events=[{'id':'middle','start':0,'end':30,'kind':'story','importance':4,'requires':[],
             'summary':'A conversation, a title card, then silent office action.',
             'selected_ranges':[{'start':0,'end':30}]}]
    transcript={'segments':[{'start':0,'end':10,'text':'Восемь уверенных слов относятся к настоящему разговору персонажей.'}],
                'words':[{'start':i,'end':i+1,'text':str(i),'probability':.9} for i in range(8)]}
    shots=[{'start':t} for t in (14,18,22,26)]
    return directory,events,transcript,shots,source


class TitleTests(unittest.TestCase):
    def test_only_current_confirmed_title_units_are_removed(self):
        directory,events,transcript,shots,source=fixture()
        original=copy.deepcopy(events)
        vision=Vision([decision(True),decision(True),decision(True),decision(True),decision(False,narrative=True),decision(False)])
        with patch('app.analysis.storyboard',side_effect=frames) as render:
            result=refine_titles(events,transcript,shots,directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],[{'start':0,'end':10},{'start':22,'end':30}])
        self.assertEqual(result[0]['excluded_title_units'],[
            {'id':'t001','start':10,'end':14},{'id':'t002','start':14,'end':18},{'id':'t003','start':18,'end':22}])
        self.assertEqual([(c.args[1],c.args[2]) for c in render.call_args_list],[(10,30),(10,14),(14,18),(18,22),(22,26),(26,30)])
        self.assertTrue(all(c.args[0]==source for c in render.call_args_list))
        self.assertEqual(events,original)
        self.assertEqual(source.read_bytes(),b'original')
        self.assertTrue(all('Street/shop/train' in call[0] for call in vision.calls))

    def test_music_signage_and_continuous_action_cannot_prove_title(self):
        directory,events,transcript,shots,_=fixture()
        vision=Vision([decision(True),decision(False),decision(True,narrative=True),decision(False),
                       decision(True,dialogue=True),decision(True,confidence=.8)])
        with patch('app.analysis.storyboard',side_effect=frames):
            result=refine_titles(events,transcript,shots,directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],events[0]['selected_ranges'])
        self.assertTrue(result[0]['story_warnings'])

    def test_spoken_title_requires_narration_flag_and_preserves_real_dialogue(self):
        for narrated,dialogue,excluded in [(False,False,False),(True,True,False),(True,False,True)]:
            with self.subTest(narrated=narrated,dialogue=dialogue):
                directory,events,_,shots,_=fixture()
                transcript={'segments':[{'start':0,'end':10,'text':'Заголовок этой истории.'}],
                    'words':[{'start':i,'end':i+1,'text':str(i),'probability':.995} for i in range(3)]}
                vision=Vision([decision(True),decision(True,narrated=narrated,dialogue=dialogue)]+[decision(False)]*5)
                with patch('app.analysis.storyboard',side_effect=frames):
                    result=refine_titles(events,transcript,shots,directory,vision,lambda *a:None,lambda:False)
                self.assertEqual(result[0]['selected_ranges'],[{'start':10 if excluded else 0,'end':30}])

    def test_disjoint_runs_share_screen_but_only_candidates_can_be_removed(self):
        directory,events,_,shots,_=fixture()
        events[0]['selected_ranges']=[{'start':10,'end':14},{'start':18,'end':22}]
        vision=Vision([decision(False),decision(False)])
        with patch('app.analysis.storyboard',side_effect=frames) as render:
            result=refine_titles(events,{'words':[],'segments':[]},shots,directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(result,events)
        self.assertEqual([(c.args[1],c.args[2]) for c in render.call_args_list],[(10,22)])

    def test_short_bumper_is_removed_at_different_source_positions(self):
        for offset in (0, 37, 180):
            with self.subTest(offset=offset):
                directory,events,_,_,_=fixture()
                events[0].update(start=offset,end=offset+12,selected_ranges=[{'start':offset,'end':offset+12}])
                transcript={'words':[{'start':offset+6+i*.75,'end':offset+6+(i+1)*.75,'text':'Сюжет.','probability':.99} for i in range(8)],
                            'segments':[{'start':offset+6,'end':offset+12,'text':'Реплика персонажа.'}]}
                vision=Vision([decision(True),decision(True)])
                with patch('app.analysis.storyboard',side_effect=frames):
                    result=refine_titles(events,transcript,[{'start':offset+4}],directory,vision,lambda *a:None,lambda:False)
                self.assertEqual(result[0]['selected_ranges'],[{'start':offset+4,'end':offset+12}])

    def test_sub_two_second_logo_does_not_merge_with_later_dialogue(self):
        directory,events,_,_,_=fixture()
        events[0].update(end=12,selected_ranges=[{'start':0,'end':12}])
        transcript={'words':[{'start':2+i,'end':3+i,'text':'Слово','probability':.99} for i in range(10)],
                    'segments':[{'start':2,'end':12,'text':'Слова персонажа.'}]}
        vision=Vision([decision(True),decision(True)])
        with patch('app.analysis.storyboard',side_effect=frames):
            result=refine_titles(events,transcript,[{'start':1.2}],directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],[{'start':1.2,'end':12}])

    def test_abstract_animation_requires_independent_continuity_proof(self):
        for same_bumper, narrative, expected in [(True,False,5),(False,False,0),(True,True,0)]:
            with self.subTest(same_bumper=same_bumper,narrative=narrative):
                directory,events,_,_,_=fixture()
                events[0].update(end=12,selected_ranges=[{'start':0,'end':12}])
                transcript={'words':[{'start':8+i*.5,'end':8+(i+1)*.5,'text':'Слово','probability':.99} for i in range(8)],
                            'segments':[{'start':8,'end':12,'text':'Сюжетный диалог.'}]}
                abstract={**decision(False),'wholly_nonnarrative':True}
                continuity={'same_production_bumper':same_bumper,'wholly_nonnarrative':True,
                            'continuous_narrative':narrative,'confidence':.95}
                vision=Vision([decision(True),abstract,decision(True),continuity])
                with patch('app.analysis.storyboard',side_effect=frames):
                    result=refine_titles(events,transcript,[{'start':2},{'start':5}],directory,
                                         vision,lambda *a:None,lambda:False)
                self.assertEqual(result[0]['selected_ranges'],[{'start':expected,'end':12}] if expected else
                                 [{'start':0,'end':2},{'start':5,'end':12}])
                self.assertIn('similar colors alone',vision.calls[-1][0])

    def test_cache_reuses_decision_and_invalidates_source_and_profile(self):
        directory,events,transcript,shots,source=fixture()
        with patch('app.analysis.storyboard',side_effect=frames):
            refine_titles(events,transcript,shots,directory,Vision([decision(True)]*6),lambda *a:None,lambda:False)
            cached=Vision([])
            result=refine_titles(events,transcript,shots,directory,cached,lambda *a:None,lambda:False)
            self.assertFalse(cached.calls)
            self.assertEqual(result[0]['titles_refinement_version'],TITLES_VERSION)
            source.write_bytes(b'changed source')
            changed=Vision([decision(False)]*5)
            refine_titles(events,transcript,shots,directory,changed,lambda *a:None,lambda:False)
            self.assertEqual(len(changed.calls),1)
            thinking=Vision([decision(False)]*5)
            thinking.thinking=True
            refine_titles(events,transcript,shots,directory,thinking,lambda *a:None,lambda:False)
            self.assertEqual(len(thinking.calls),1)

    def test_cancel_inside_query_propagates_and_does_not_publish_partial_exclusion(self):
        directory,events,transcript,shots,_=fixture()
        vision=Vision([decision(True)])
        with patch('app.analysis.storyboard',side_effect=frames):
            with self.assertRaises(InterruptedError):
                refine_titles(events,transcript,shots,directory,vision,lambda *a:None,lambda:bool(vision.calls))
        self.assertFalse(list((directory/'title_units').glob('*.json')))
        self.assertNotIn('excluded_title_units',events[0])

    def test_unknown_boolean_and_missing_source_preserve_scene(self):
        directory,events,transcript,shots,_=fixture()
        vision=Vision([decision(True),{**decision(True),'visible_production_title':'true'}]+[decision(False)]*4)
        with patch('app.analysis.storyboard',side_effect=frames):
            result=refine_titles(events,transcript,shots,directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],events[0]['selected_ranges'])
        self.assertTrue(result[0]['story_warnings'])
        (directory/'source.json').unlink()
        vision=Vision([])
        result=refine_titles(events,transcript,shots,directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],events[0]['selected_ranges'])
        self.assertFalse(vision.calls)

    def test_confident_negative_group_screen_performs_no_per_unit_queries(self):
        directory,events,transcript,shots,_=fixture()
        vision=Vision([decision(False)])
        with patch('app.analysis.storyboard',side_effect=frames) as render:
            result=refine_titles(events,transcript,shots,directory,vision,lambda *a:None,lambda:False)
        self.assertEqual(result[0]['selected_ranges'],events[0]['selected_ranges'])
        self.assertEqual(len(vision.calls),1)
        self.assertEqual(render.call_count,1)
