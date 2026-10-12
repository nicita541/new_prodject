import unittest
from app.speech_handles import expand_ranges, ending_matches, semantic_ranges
from app.planner import build_plan


class SpeechHandleTests(unittest.TestCase):
    def test_semantic_clock_rejects_forged_padding_and_nonfinite_ranges(self):
        transcript={'words':[{'start':2,'end':3,'text':'Ответ'}]}
        core=[{'start':2,'end':3}]
        plan={'semantic_ranges':core,'parts':[{'cuts':[{'start':1.82,'end':3.55}]}]}
        self.assertEqual(semantic_ranges(plan,[],transcript,10),core)
        for bad in ([{'start':1.7,'end':3.55}], [{'start':1.82,'end':4}]):
            with self.assertRaises(ValueError):
                semantic_ranges({**plan,'parts':[{'cuts':bad}]},[],transcript,10)
        for bad in ('bad',[{'start':True,'end':3}],[{'start':float('nan'),'end':3}],[] ):
            with self.assertRaises(ValueError):
                semantic_ranges({**plan,'semantic_ranges':bad},[],transcript,10)

    def test_structured_selection_preserves_speech_margins(self):
        transcript={'words':[{'start':2,'end':3,'text':'Ответ.'}],
                    'segments':[{'start':2,'end':3,'text':'Ответ.'}]}
        a={'probe':{'duration':10,'width':1920,'height':1080,'has_audio':True},
           'transcript':transcript,'shots':[],
           'events':[{'id':'e','kind':'story','importance':4,'start':0,'end':10,'requires':[],
                      'focus':[],'story_structure':{},'selected_ranges':[{'start':2,'end':3}],
                      'unit_selection_version':1}]}
        cut=build_plan(a)['parts'][0]['cuts'][0]
        self.assertAlmostEqual(cut['start'],1.82)
        self.assertAlmostEqual(cut['end'],3.55)

    def test_never_takes_omitted_neighbor_word(self):
        transcript={'words':[{'start':1,'end':2,'text':'До'},
            {'start':2.1,'end':3,'text':'Ответ'}, {'start':3.2,'end':4,'text':'После'}]}
        piece=expand_ranges([{'start':2.1,'end':3}],transcript,10)[0]
        self.assertAlmostEqual(piece['start'],2.04)
        self.assertAlmostEqual(piece['end'],3.16)

    def test_title_is_a_barrier(self):
        piece=expand_ranges([{'start':2,'end':3}],{'words':[{'start':2,'end':3}]},10,
            [{'start':0,'end':1.95},{'start':3.1,'end':4}])[0]
        self.assertEqual(piece,{'start':1.95,'end':3.1})

    def test_verified_ending_tail_cannot_include_new_speech_or_gap(self):
        cuts=[{'start':1,'end':3.5}]
        self.assertTrue(ending_matches(3,3.5,{'words':[{'start':2,'end':3}]},cuts))
        self.assertFalse(ending_matches(3,3.5,{'words':[{'start':3.2,'end':3.4}]},cuts))
        self.assertFalse(ending_matches(3,3.5,{'words':[]},[{'start':3.1,'end':3.5}]))


if __name__=='__main__':
    unittest.main()
