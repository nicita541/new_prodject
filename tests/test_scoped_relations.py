"""Native cross-owner dependency mechanisms using captured fake provider calls."""
import copy
import json
from pathlib import Path
import unittest

from app import dialogue_relations as dialogue, story_structure_pass as structure
from app.scoped_relations import recover_relations
from tests.test_media import workspace_directory
from tests.test_story_structure_pass import fixture, facts


def episode(count=24):
    event, transcript = fixture(count)
    for index,word in enumerate(transcript['words']):
        if index % 2:
            word['text'] = 'Она в нижнем ящике.'
            event['unit_evidence'][index]['speech_quote'] = word['text']
    transcript['segments'] = copy.deepcopy(transcript['words'])
    events = []
    for index,unit in enumerate(event['units']):
        events.append({**copy.deepcopy(event),'id':f'owner_{index:03d}', 'scene_id':f'scene_{index:03d}',
            'start':unit['start'],'end':unit['end'],'units':[copy.deepcopy(unit)],
            'unit_evidence':[copy.deepcopy(event['unit_evidence'][index])],
            'selected_ranges':[{'start':unit['start'],'end':unit['end']}]})
    return events,transcript


def citation(node):
    return {'ref':node['ref'],'proof':node['proofs'][0]['id'],'quote':node['ASR']}


class CapturedProvider:
    model = 'authored-dp-model'
    projector = 'authored-text'
    thinking = False
    cache_profile = {'provider':'deepseek_plan'}
    def __init__(self):
        self.calls=[]
    def token_count(self,prompt):
        return 1000
    def query(self,prompt,image=None,max_tokens=None,schema=None):
        payload = json.loads(prompt.rsplit('\n',1)[1])
        self.calls.append({'payload':payload,'schema':schema})
        current = {(n['ref']['event'],n['ref']['unit']) for n in payload['CURRENT']}
        nodes = {tuple(n['ref'].values()):n for n in [*payload['CURRENT'],*payload['CONTEXT_ONLY'],
            *(m['source'] for m in payload.get('MEMORY',[]))]}
        ordered = sorted(nodes.values(),key=lambda n:n['start'])
        pairs=[]
        spoken=[n for n in ordered if n['ASR']]
        for left,right in zip(spoken,spoken[1:]):
            if (left['ASR'].startswith('Где') and right['ASR'].startswith('Она')
                    and any(tuple(n['ref'].values()) in current for n in (left,right))):
                pairs.append((left,right))
        if 'canonical_entities' in schema.get('properties',{}):
            return {'resolved':True,'understanding_confidence':.95,'structure_confidence':.95,
                'units':[{'ref':n['ref'],'roles':['transition' if not n['ASR'] else 'setup' if n['ASR'].startswith('Где') else 'payoff'],
                    'before':facts(),'after':facts(),'confidence':.95,'viewer_interest':[],
                    'evidence':'Exact independently accepted source speech supplies this story function.',
                    'support':[citation(n)]} for n in payload['CURRENT']],
                'relations':[{'type':'response','from':q['ref'],'to':a['ref'],'confidence':.95,
                    'evidence':'Exact original answer directly resolves the source question.',
                    'support':[citation(q),citation(a)]} for q,a in pairs],
                'arcs':[{'anchor':q['ref'],'members':[{'ref':q['ref'],'role':'setup'},{'ref':a['ref'],'role':'payoff'}],
                    'closed':True,'closing_unit':a['ref'],'confidence':.95,
                    'evidence':'The supplied answer completes this independently proved source exchange.',
                    'support':[citation(q),citation(a)]} for q,a in pairs],
                'canonical_entities':[],'limitations':[]}
        participants = {tuple(n['ref'].values()) for pair in pairs for n in pair}
        return {'resolved':True,'understanding_confidence':.95,'relation_confidence':.95,
            'pairs':[{'question':q['ref'],'answer':a['ref'],'question_quote':q['ASR'],'answer_quote':a['ASR'],
                'requires_answer':True,'confidence':.95,'evidence':'The exact answer resolves this actual spoken source question.',
                'support':[citation(q),citation(a)]} for q,a in pairs],
            'coverage':[{'ref':n['ref'],'decision':'paired' if tuple(n['ref'].values()) in participants else 'not_dialogue_dependency',
                'confidence':.95,'evidence':'The original accepted source speech supports this explicit dialogue ownership.',
                'support':[citation(n)]} for n in payload['CURRENT']], 'limitations':[]}


def initial(events,transcript,directory,vision):
    story = structure.infer_story_structure(events,transcript,directory,vision,lambda:False)
    relations = dialogue.infer_dialogue_relations(story['events'],transcript,directory,vision,lambda:False,relations=story)
    return {'events':dialogue.attach_dialogue_result(story['events'],relations),
            'story_structure':story,'dialogue_relations':relations}


class ScopedRelationsTests(unittest.TestCase):
    def test_known_far_causal_endpoint_is_current_source_context_and_warm_reusable(self):
        class FarProvider(CapturedProvider):
            def query(self,prompt,image=None,max_tokens=None,schema=None):
                raw=super().query(prompt,image,max_tokens,schema)
                if 'canonical_entities' not in schema.get('properties',{}):
                    return raw
                payload=self.calls[-1]['payload']
                supplied={n['ref']['event']:n for n in [*payload['CURRENT'],*payload['CONTEXT_ONLY'],
                    *(m['source'] for m in payload.get('MEMORY',[]))]}
                if {'owner_002','owner_008'} <= supplied.keys() and any(
                        n['ref']['event'] in ('owner_002','owner_008') for n in payload['CURRENT']):
                    left,right=supplied['owner_002'],supplied['owner_008']
                    raw['relations'].append({'type':'cause','from':left['ref'],'to':right['ref'],
                        'confidence':.95,'evidence':'Both independent source proofs establish this concrete causal dependency.',
                        'support':[citation(left),citation(right)]})
                return raw
        events,transcript=episode(12)
        with workspace_directory('scoped-far-') as directory:
            directory=Path(directory)
            previous=initial(events,transcript,directory,FarProvider())
            self.assertTrue(any(r['type']=='cause' for r in previous['story_structure']['relations']))
            changed=copy.deepcopy(previous['events'])
            changed[2]['unit_evidence'][0]['checkpoint']='b'*64
            vision=FarProvider()
            result=recover_relations(changed,transcript,previous,{'owner_002'},directory,vision,lambda:False)
            query=next(c['payload'] for c in vision.calls if 'MEMORY' in c['payload']
                and any(n['ref']['event']=='owner_002' for n in c['payload']['CURRENT']))
            self.assertIn('owner_008',{n['ref']['event'] for n in query['CONTEXT_ONLY']})
            warm=FarProvider()
            repeated=recover_relations(result['events'],transcript,result,set(),directory,warm,lambda:False)
        self.assertEqual(result['story_structure']['status'],'accepted')
        self.assertTrue(any(r['type']=='cause' and r['from']['event']=='owner_002'
                            and r['to']['event']=='owner_008' for r in result['story_structure']['relations']))
        self.assertEqual(warm.calls,[])
        self.assertEqual(repeated['story_structure']['status'],'accepted')

    def test_one_changed_proof_dispatches_only_dependent_owners_and_merges_episode(self):
        events,transcript = episode()
        with workspace_directory('scoped-relations-') as directory:
            directory = Path(directory)
            first = initial(events,transcript,directory,CapturedProvider())
            changed = copy.deepcopy(first['events'])
            changed[12]['unit_evidence'][0]['checkpoint'] = 'b'*64
            vision = CapturedProvider()
            result = recover_relations(changed,transcript,first,{'owner_012'},directory,vision,lambda:False)
        self.assertTrue(vision.calls)
        sent = {n['ref']['event'] for call in vision.calls for n in call['payload']['CURRENT']}
        self.assertIn('owner_012',sent)
        self.assertNotIn('owner_000',sent)
        self.assertNotIn('owner_023',sent)
        self.assertEqual(result['story_structure']['status'],'accepted')
        self.assertEqual(result['dialogue_relations']['status'],'accepted')
        self.assertEqual(len(result['events']),24)
        self.assertEqual(len(result['story_structure']['coverage']),24)
        self.assertEqual(len(result['dialogue_relations']['coverage']),24)
        self.assertEqual(result['events'][0]['selected_ranges'],events[0]['selected_ranges'])
        self.assertTrue(any(r['from']['event'] != r['to']['event'] for r in result['story_structure']['relations']))

    def test_warm_no_target_and_cloud_switch_dispatch_nothing_preserving_producer(self):
        events,transcript = episode(8)
        with workspace_directory('scoped-cloud-') as directory:
            directory = Path(directory)
            first = initial(events,transcript,directory,CapturedProvider())
            switched = CapturedProvider()
            switched.model='authored-ag-model'
            switched.cache_profile={'provider':'antigravity_manual'}
            result = recover_relations(first['events'],transcript,first,set(),directory,switched,lambda:False)
        self.assertEqual(switched.calls,[])
        self.assertEqual(result['story_structure']['status'],'accepted')
        self.assertEqual(result['dialogue_relations']['status'],'accepted')
        self.assertEqual(result['story_structure']['history'][0]['producer']['profile']['provider'],'deepseek_plan')

    def test_previous_aggregate_can_reuse_exact_contracts_when_checkpoint_file_is_missing(self):
        events,transcript = episode(8)
        with workspace_directory('scoped-history-') as directory:
            directory = Path(directory)
            first = initial(events,transcript,directory,CapturedProvider())
            for aggregate,folder in ((first['story_structure'],'story-structure'),(first['dialogue_relations'],'dialogue-relations')):
                for row in aggregate['history']:
                    (directory/folder/(row['checkpoint']+'.json')).unlink()
            vision=CapturedProvider()
            result = recover_relations(first['events'],transcript,first,set(),directory,vision,lambda:False)
        self.assertEqual(vision.calls,[])
        self.assertEqual(result['story_structure']['status'],'accepted')
        self.assertEqual(result['dialogue_relations']['status'],'accepted')

    def test_legacy_label_without_exact_contract_never_grants_acceptance_or_whole_episode_dispatch(self):
        events,transcript = episode(8)
        previous={'events':copy.deepcopy(events),'story_structure':{'status':'accepted','history':[]},
                  'dialogue_relations':{'status':'accepted','history':[]}}
        with workspace_directory('scoped-legacy-') as directory:
            vision=CapturedProvider()
            result=recover_relations(events,transcript,previous,set(),Path(directory),vision,lambda:False)
        self.assertEqual(vision.calls,[])
        self.assertEqual(result['story_structure']['status'],'unresolved')
        self.assertEqual(result['dialogue_relations']['status'],'unresolved')

    def test_foreign_recovery_owner_rejected_before_any_provider_request(self):
        events,transcript=episode(4)
        with workspace_directory('scoped-foreign-') as directory:
            vision=CapturedProvider()
            with self.assertRaises(ValueError):
                recover_relations(events,transcript,{}, {'foreign'},Path(directory),vision,lambda:False)
        self.assertEqual(vision.calls,[])

    def test_replaced_owner_rechecks_surviving_endpoints_without_stale_references(self):
        events,transcript=episode(24)
        with workspace_directory('scoped-replacement-') as directory:
            directory=Path(directory)
            previous=initial(events,transcript,directory,CapturedProvider())
            changed=copy.deepcopy(previous['events'])
            changed[12]['id']='replacement'
            changed[12]['scene_id']='replacement-scene'
            vision=CapturedProvider()
            result=recover_relations(changed,transcript,previous,{'replacement'},directory,vision,lambda:False)
        self.assertEqual(result['story_structure']['status'],'accepted')
        self.assertEqual(result['dialogue_relations']['status'],'accepted')
        sent={n['ref']['event'] for call in vision.calls for n in call['payload']['CURRENT']}
        self.assertIn('replacement',sent)
        self.assertIn('owner_013',sent)
        self.assertNotIn('owner_000',sent)
        self.assertNotIn('owner_012',json.dumps(result))

    def test_actual_split_keeps_later_cohort_grouping_and_initial_packing(self):
        events,transcript=episode(30)
        with workspace_directory('scoped-insert-') as directory:
            directory=Path(directory)
            initial_vision=CapturedProvider()
            previous=initial(events,transcript,directory,initial_vision)
            self.assertEqual(len(initial_vision.calls),10+5)
            changed=copy.deepcopy(previous['events'])
            left,right=copy.deepcopy(changed[12]),copy.deepcopy(changed[12])
            boundary=left['start']+2.5
            left.update(id='split_left',scene_id='split_left',end=boundary,
                        selected_ranges=[{'start':left['start'],'end':boundary}])
            left['units'][0]['end']=boundary
            left['unit_evidence'][0].update(view_end=boundary,checkpoint='b'*64)
            right.update(id='split_right',scene_id='split_right',start=boundary,
                         selected_ranges=[{'start':boundary,'end':right['end']}])
            right['units'][0].update(id='silent_new_unit',start=boundary)
            right['unit_evidence']=[{'unit':'silent_new_unit','decision':'keep','kind':'physical_action',
                'confidence':.95,'evidence':'A concrete source action is independently proved inside this new whole source unit.',
                'speech_quote':'','frame_count':1,'frame_indices':[1],
                'frame_times':[(boundary+right['end'])/2],'view_start':boundary,'view_end':right['end'],'checkpoint':'c'*64}]
            changed[12:13]=[left,right]
            vision=CapturedProvider()
            result=recover_relations(changed,transcript,previous,{'split_left','split_right'},directory,vision,lambda:False)
        sent={n['ref']['event'] for c in vision.calls for n in c['payload']['CURRENT']}
        self.assertIn('split_left',sent)
        self.assertIn('split_right',sent)
        self.assertNotIn('owner_000',sent)
        self.assertNotIn('owner_029',sent)
        self.assertEqual(result['story_structure']['status'],'accepted')
        self.assertEqual(result['dialogue_relations']['status'],'accepted')
        self.assertEqual(len(result['story_structure']['coverage']),31)
        self.assertEqual(len(result['dialogue_relations']['coverage']),31)

    def test_unrelated_unselected_source_asr_does_not_invalidate_native_requests(self):
        events,transcript=episode(8)
        with workspace_directory('scoped-unrelated-asr-') as directory:
            directory=Path(directory)
            previous=initial(events,transcript,directory,CapturedProvider())
            unrelated={'start':1000,'end':1001,'text':'UNRELATED_SOURCE_SENTINEL'}
            changed=copy.deepcopy(transcript)
            changed['words'].append(unrelated)
            changed['segments'].append(copy.deepcopy(unrelated))
            vision=CapturedProvider()
            result=recover_relations(previous['events'],changed,previous,set(),directory,vision,lambda:False)
        self.assertEqual(vision.calls,[])
        self.assertEqual(result['story_structure']['status'],'accepted')
        self.assertEqual(result['dialogue_relations']['status'],'accepted')

    def test_exact_identity_cannot_bypass_native_validation_of_corrupt_output(self):
        from app.content_identity import digest
        events,transcript=episode(8)
        with workspace_directory('scoped-corrupt-') as directory:
            directory=Path(directory)
            previous=initial(events,transcript,directory,CapturedProvider())
            entry=previous['story_structure']['history'][0]
            path=directory/'story-structure'/(entry['checkpoint']+'.json')
            damaged=json.loads(path.read_text('utf-8'))
            damaged['decision']['units'][0]['ref']={'event':'foreign','unit':'foreign'}
            damaged['decision_hash']=digest(damaged['decision'])
            path.write_text(json.dumps(damaged),'utf-8')
            previous['story_structure']['history']=[]
            vision=CapturedProvider()
            result=recover_relations(previous['events'],transcript,previous,{'owner_000'},directory,vision,lambda:False)
        self.assertTrue(vision.calls)
        self.assertEqual(result['story_structure']['status'],'accepted')
        self.assertNotIn('foreign',json.dumps(result['story_structure']['units']))

    def test_inherited_source_images_are_verified_before_cached_relation_reuse(self):
        import hashlib
        events,transcript=episode(2)
        with workspace_directory('scoped-image-proof-') as directory:
            directory=Path(directory)
            (directory/'analysis.meta.json').write_text(json.dumps({'source':'1'*64}),'utf-8')
            native=directory/'selection-adjudication'
            native.mkdir()
            image=directory/'original-frame.jpg'
            image.write_bytes(b'original immutable source frame')
            (native/('a'*64+'.json')).write_text(json.dumps({'source_evidence':{
                'source':{'sha256':'1'*64},'images':{str(image):hashlib.sha256(image.read_bytes()).hexdigest()}}}),'utf-8')
            first=initial(events,transcript,directory,CapturedProvider())
            self.assertEqual(first['story_structure']['status'],'accepted')
            image.write_bytes(b'changed source frame')
            vision=CapturedProvider()
            result=structure.infer_story_structure(first['events'],transcript,directory,vision,lambda:False,
                previous=first['story_structure'],dispatch_refs=set())
        self.assertEqual(vision.calls,[])
        self.assertEqual(result['status'],'unresolved')
        self.assertIn('image changed',result['history'][-1]['error'])
