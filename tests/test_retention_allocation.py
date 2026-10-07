"""Authored mechanism tests; these are not production semantic quality proof."""
import copy
import unittest
from app.retention_allocation import allocate_retention, mandatory_ranges


def event(identifier,start,end,mandatory=False):
    return {'id':identifier,'start':start,'end':end,'selected_ranges':[{'start':start,'end':end}],
        'selection_status':'accepted','understanding_status':'accepted',
        'understanding_confidence':.95,'selection_confidence':.95,
        'units':[{'id':'u0','start':start,'end':end,'text':''}],
        'narrative_bridge':mandatory,'unit_evidence':[{'unit':'u0','kind':'state_transition' if mandatory else 'physical_action',
            'decision':'keep','confidence':.95,'evidence':'В CURRENT руки персонажа застёгивают видимый ремень.',
            'frame_indices':[1],'frame_count':1,'frame_times':[(start+end)/2],'speech_quote':''}]}


def unchanged(events,selected,transcript,duration):
    return {'events':events,'selected_ids':sorted(selected),'bridges':[],'warnings':[],'transitions':[]}


class RetentionAllocationTests(unittest.TestCase):
    def test_optional_large_arc_does_not_force_avoidable_seed_overflow(self):
        events=[event(str(i),i*10,i*10+4) for i in range(3)]
        result=allocate_retention(events,{e['id']:e['selected_ranges'] for e in events},
            ['0','1','2'],[{'event_ids':['0','1','2'],'uncertain':False}],{},30,
            {'optimal':7,'max':10},unchanged)
        self.assertEqual(result['retained_duration'],8)
        self.assertEqual(result['overflow_reasons'],[])

    def test_later_optional_addition_preserves_prior_required_bridge_cost_and_proof(self):
        events=[event('mandatory',0,2,True),event('first',10,14),event('bridge',20,24),event('last',30,31)]
        proof={'source_event':'bridge','ranges':[{'start':20,'end':24}],
            'reason':'evidenced_state_transition','evidence':[{'kind':'action_unit','unit_id':'u0'}]}
        def continuity(source,selected,transcript,duration):
            result=unchanged(source,selected,transcript,duration)
            if 'first' in selected and 'bridge' not in selected:
                result['selected_ids'].append('bridge'); result['bridges']=[copy.deepcopy(proof)]
            return result
        result=allocate_retention(events,{e['id']:e['selected_ranges'] for e in events},
            ['first','last'],[],{},40,{'optimal':12,'max':12},continuity)
        self.assertEqual(result['retained_duration'],11)
        self.assertEqual(result['mandatory_duration'],6)
        self.assertEqual(result['optional_duration'],5)
        self.assertEqual(result['continuity']['bridges'],[proof])
        self.assertIn('required_continuity_context',result['selection_reasons']['bridge'])

    def test_proven_mandatory_ranges_are_reserved_before_higher_scored_optional(self):
        events=[event('optional',0,9),event('mandatory',20,22,True),event('small',30,35)]
        snapshot=copy.deepcopy(events)
        result=allocate_retention(events,{e['id']:e['selected_ranges'] for e in events},
            ['optional','small'],[],{},50,{'optimal':9,'max':10},unchanged)
        self.assertEqual(result['selected_ids'],['mandatory','small'])
        self.assertEqual(result['mandatory_duration'],2)
        self.assertEqual(result['optional_duration'],5)
        self.assertEqual(events,snapshot)

    def test_candidate_cost_uses_union_of_source_ranges_not_scene_envelope(self):
        events=[event('wide',0,100),event('overlap',0,100)]
        result=allocate_retention(events,{'wide':[{'start':10,'end':15}],
            'overlap':[{'start':12,'end':18}]},['wide','overlap'],[],{},100,
            {'optimal':9,'max':10},unchanged)
        self.assertEqual(result['selected_ids'],['overlap','wide'])
        self.assertEqual(result['retained_duration'],8)

    def test_required_continuity_is_costed_before_accepting_optional_addition(self):
        events=[event('large',0,8),event('mandatory',20,22,True),event('bridge',30,34),event('small',40,44)]
        def continuity(source,selected,transcript,duration):
            result=unchanged(source,selected,transcript,duration)
            if 'large' in selected:
                result['selected_ids'].append('bridge')
                result['bridges']=[{'source_event':'bridge','ranges':[{'start':30,'end':34}],
                    'evidence':[{'kind':'action_unit','unit_id':'u0'}],'reason':'evidenced_state_transition'}]
            return result
        result=allocate_retention(events,{e['id']:e['selected_ranges'] for e in events},
            ['large','small'],[],{},50,{'optimal':9,'max':10},continuity)
        self.assertEqual(result['selected_ids'],['mandatory','small'])
        self.assertNotIn('bridge',result['selected_ids'])
        self.assertIn('adaptive_max_including_mandatory_context',result['selection_reasons']['large'])

    def test_mandatory_overflow_keeps_full_unit_and_records_specific_proof_and_excess(self):
        events=[event('mandatory',0,12,True)]
        result=allocate_retention(events,{},[],[],{},20,{'optimal':8,'max':10},unchanged)
        self.assertEqual(result['selected_ranges']['mandatory'],[{'start':0,'end':12}])
        self.assertEqual(result['optional_budget'],0)
        reason=result['overflow_reasons'][0]
        self.assertEqual(reason['reason'],'mandatory_source_context_exceeds_max')
        self.assertEqual(reason['excess'],2)
        self.assertEqual(reason['proofs'][0]['unit'],'u0')

    def test_naked_bridge_bad_frame_or_excluded_action_is_not_mandatory(self):
        source=event('bridge',0,4,True)
        for change in ('naked','foreign','excluded'):
            e=copy.deepcopy(source)
            if change=='naked': e['unit_evidence']=[]
            elif change=='foreign': e['unit_evidence'][0]['frame_times']=[8]
            else: e['excluded_title_units']=[{'start':0,'end':4}]
            with self.subTest(change=change):
                self.assertEqual(mandatory_ranges([e]),({},[]))


if __name__=='__main__':unittest.main()
