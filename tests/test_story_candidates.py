"""Authored source-contract fixtures; these tests do not assess real editorial quality."""
import copy
import unittest

from app import story_candidates as candidates
from app.config import ROOT


SOURCE_SHA = 'a' * 64


def authored_screen_record(analysis, case, plan):
    """A deterministic mechanism fixture, never evidence of real editorial quality."""
    from app.candidate_screen import CRITERIA, project_candidate, bind_record
    projection = project_candidate(analysis, case, plan)
    units = projection['payload']['units']
    proofs = []
    for phase, unit in zip(('opening', 'development', 'ending'),
                           (units[0], units[len(units) // 2], units[-1])):
        spoken = bool(unit['text'])
        proofs.append({'phase': phase, 'unit': unit['id'], 'mode': 'speech' if spoken else 'visual',
            'quote': unit['text'] if spoken else '', 'frames': [] if spoken else unit['frame_indices'][:1],
            'evidence': 'AUTHORED mechanism fixture for this retained output interval.'})
    return bind_record(projection, {'resolved': True, 'is_story': True,
        'title': 'AUTHORED mechanism fixture only', 'criteria': {name: True for name in CRITERIA},
        'issues': [], 'proofs': proofs})


def source_fixture():
    utterances = [
        {'start': 0., 'end': 20., 'text': 'Can you open the door?'},
        {'start': 20., 'end': 40., 'text': 'Yes, the door is now open.'},
        {'start': 40., 'end': 60., 'text': 'Thank you, we can leave.'},
    ]
    return {
        'probe': {'duration': 60., 'width': 640, 'height': 360, 'fps': 25., 'has_audio': True},
        'transcript': {'segments': copy.deepcopy(utterances), 'words': copy.deepcopy(utterances)},
        'shots': [{'id': f's{index}', 'start': start, 'end': start + 10.}
                  for index, start in enumerate(range(0, 60, 10))],
        'source_sha256': SOURCE_SHA,
    }


def candidate_fixture(analysis=None):
    analysis = source_fixture() if analysis is None else copy.deepcopy(analysis)
    episode_map = {
        'source_sha256': SOURCE_SHA, 'authority': 'hypothesis_only',
        'windows': [{'id': 'w1', 'start': 0., 'end': 60.}],
        'hypotheses': [{'id': 'h1', 'window_ids': ['w1'], 'prerequisite_window_ids': []}],
    }
    case = candidates.candidate_cases(analysis, episode_map, SOURCE_SHA)[0]
    for unit in case['units']:
        for time in (unit['start'] + .04, unit['end'] - .04):
            index = len(case['frames']) + 1
            case['frames'].append({'index': index, 'unit': unit['id'], 'time': time,
                'sha256': f'{index:064x}', 'path': str(ROOT/'temp'/f'authored-mechanism-frame-{index}.jpg')})
    units = case['units']
    proposal = {'viable': True, 'title': 'The open door', 'reason': 'A complete source exchange.',
                'interest': 3, 'cuts': [{'first': units[0]['id'], 'last': units[-1]['id']}]}
    plan, _ = candidates.prototype_plan(analysis, case, proposal)
    review = {
        'resolved': True, 'is_story': True,
        'criteria': {name: True for name in candidates.CRITERIA},
        'proofs': [{'phase': phase, 'unit': unit['id'], 'mode': 'speech',
                    'quote': unit['text'], 'frames': [], 'motion': [],
                    'evidence': 'The original exchange supplies this story beat.'}
                   for phase, unit in zip(('opening', 'development', 'ending'), units)],
        'required_units': [], 'requested_units': [], 'issues': [],
        'dialogue': [
            {'unit': units[0]['id'], 'quote': units[0]['text'], 'status': 'question_answered',
             'partners': [units[1]['id']], 'evidence': 'The next original utterance answers this request.'},
            {'unit': units[1]['id'], 'quote': units[1]['text'], 'status': 'answer',
             'partners': [units[0]['id']], 'evidence': 'This original reply answers the retained question.'},
            {'unit': units[2]['id'], 'quote': units[2]['text'], 'status': 'self_contained',
             'partners': [], 'evidence': 'The original closing utterance states the outcome.'},
        ],
        'boundaries': [{'cut': index, 'side': side, 'safe': True,
                        'frames': [candidates.boundary_anchor(case, cut, side)],
                        'evidence': 'This retained original edge preserves the source action and speech.'}
                       for index, cut in enumerate(plan['parts'][0]['cuts'], 1)
                       for side in ('start', 'end')],
    }
    record = {'case': case, 'proposal': proposal, 'review': review,
              'timeline_digest': candidates.timeline_digest(plan), 'status': 'ready',
              'screen': authored_screen_record(analysis, case, plan)}
    return analysis, record, plan


def edge_utterance_fixture():
    analysis = source_fixture()
    utterance = {'start': 20., 'end': 40., 'text': 'The complete original utterance.'}
    analysis['transcript'] = {'words': [copy.deepcopy(utterance)], 'segments': [copy.deepcopy(utterance)]}
    episode_map = {'source_sha256': SOURCE_SHA, 'authority': 'hypothesis_only',
                   'windows': [{'id': 'middle', 'start': 20., 'end': 40.}],
                   'hypotheses': [{'id': 'middle_hypothesis', 'window_ids': ['middle'],
                                   'prerequisite_window_ids': []}]}
    case = candidates.candidate_cases(analysis, episode_map, SOURCE_SHA)[0]
    proposal = {'viable': True, 'title': 'Authored edge selection', 'reason': 'A test proposal only.',
                'interest': 1, 'cuts': [{'first': case['units'][0]['id'], 'last': case['units'][0]['id']}]}
    return analysis, case, proposal


def establishing_reaction_fixture(*, multiple_cuts=False):
    analysis = source_fixture()
    utterances = [{'start': start, 'end': start + 5., 'text': text}
                  for start, text in ((10., 'The door is locked.'),
                                      (20., 'I will use this key.'),
                                      (40., 'The door is open now.'))]
    analysis['transcript'] = {'words': copy.deepcopy(utterances), 'segments': copy.deepcopy(utterances)}
    episode_map = {'source_sha256': SOURCE_SHA, 'authority': 'hypothesis_only',
                   'windows': [{'id': 'all', 'start': 0., 'end': 60.}],
                   'hypotheses': [{'id': 'with_original_reactions', 'window_ids': ['all'],
                                   'prerequisite_window_ids': []}]}
    case = candidates.candidate_cases(analysis, episode_map, SOURCE_SHA)[0]
    for unit in case['units']:
        for time in (unit['start'] + .04, unit['end'] - .04):
            index = len(case['frames']) + 1
            case['frames'].append({'index': index, 'unit': unit['id'], 'time': time, 'sha256': f'{index:064x}',
                                  'path': str(ROOT/'temp'/f'authored-mechanism-frame-{index}.jpg')})
    units = case['units']
    spans = ((0., 30.), (40., 60.)) if multiple_cuts else ((0., 60.),)
    proposal = {'viable': True, 'title': 'Original establishing shot and reaction', 'reason': 'Authored test only.',
                'interest': 3, 'cuts': [{'first': next(u['id'] for u in units if u['start'] == start),
                                       'last': next(u['id'] for u in units if u['end'] == end)}
                                      for start, end in spans]}
    plan, _ = candidates.prototype_plan(analysis, case, proposal)
    speech = [unit for unit in candidates.selected_units(case, proposal) if unit['text']]
    review = {'resolved': True, 'is_story': True, 'criteria': {name: True for name in candidates.CRITERIA},
        'proofs': [{'phase': phase, 'unit': unit['id'], 'mode': 'speech', 'quote': unit['text'],
                    'frames': [], 'motion': [], 'evidence': 'An authored original source beat.'}
                   for phase, unit in zip(('opening', 'development', 'ending'), speech)],
        'required_units': [], 'requested_units': [], 'issues': [],
        'dialogue': [{'unit': unit['id'], 'quote': unit['text'], 'status': 'self_contained',
                      'partners': [], 'evidence': 'An authored complete source statement.'} for unit in speech],
        'boundaries': [{'cut': index, 'side': side, 'safe': True,
                        'frames': [candidates.boundary_anchor(case, cut, side)],
                        'evidence': 'An authored check of this actual retained cut edge.'}
                       for index, cut in enumerate(plan['parts'][0]['cuts'], 1) for side in ('start', 'end')]}
    return analysis, {'case': case, 'proposal': proposal, 'review': review,
                      'timeline_digest': candidates.timeline_digest(plan), 'status': 'ready',
                      'screen': authored_screen_record(analysis, case, plan)}, plan


def authored_join_rows(case, plan, version):
    rows = []
    for join in candidates.source_joins(case, plan):
        row = {'after_cut': join['after_cut'], 'safe_to_omit': True, 'classification': 'incidental',
            'frames': [join['left_frame'], *join['omitted_frames'], join['right_frame']],
            'evidence': 'AUTHORED mechanism fixture: this observed gap contains only incidental waiting.'}
        if version == 2:
            row.update(change={'kind': 'none',
                'before': {'frame': join['omitted_frames'][0], 'state': 'The original waiting state.'},
                'after': {'frame': join['omitted_frames'][-1], 'state': 'The original waiting state.'}},
                retained_witness={'frames': [], 'evidence': ''})
        rows.append(row)
    return rows


def source_join_fixture(*, multiple_cuts=True, version=2):
    analysis, record, plan = establishing_reaction_fixture(multiple_cuts=multiple_cuts)
    analysis['source_join_policy'] = {'version': version}
    record['case']['source_join_policy'] = {'version': version}
    if version == 2:
        for join in candidates.source_joins(record['case'], plan):
            time = (join['start']+join['end'])/2
            owner = next(unit for unit in record['case']['units'] if unit['start'] <= time < unit['end'])
            index = max(frame['index'] for frame in record['case']['frames'])+1
            record['case']['frames'].append({'index': index, 'unit': owner['id'], 'time': time,
                'sha256': f'{index:064x}', 'path': str(ROOT/'temp'/f'authored-mechanism-frame-{index}.jpg')})
    record['review']['joins'] = authored_join_rows(record['case'], plan, version)
    return analysis, record, plan


def source_restoration_fixture(*, boundary_neighbor=False):
    """Authored omitted event spanning three units, not real editorial evidence."""
    analysis, record, _ = establishing_reaction_fixture(multiple_cuts=True)
    analysis['source_join_policy'] = {'version': 2}
    gap_shots = ((30., 33.), (33., 36.), (36., 39.), (39., 40.)) if boundary_neighbor else (
        (30., 33.), (33., 36.), (36., 40.))
    analysis['shots'][3:4] = [{'id': f'gap{index}', 'start': a, 'end': b}
        for index, (a, b) in enumerate(gap_shots)]
    episode_map = {'source_sha256': SOURCE_SHA, 'authority': 'hypothesis_only',
        'windows': [{'id': 'all', 'start': 0., 'end': 60.}],
        'hypotheses': [{'id': 'restore', 'window_ids': ['all'], 'prerequisite_window_ids': []}]}
    case, = candidates.candidate_cases(analysis, episode_map, SOURCE_SHA)
    for unit in case['units']:
        for time in (unit['start']+.04, (unit['start']+unit['end'])/2, unit['end']-.04):
            index = len(case['frames'])+1
            case['frames'].append({'index': index, 'unit': unit['id'], 'time': time,
                'sha256': f'{index:064x}', 'path': str(ROOT/'temp'/f'authored-mechanism-frame-{index}.jpg')})
    record['case'] = case
    plan, _ = candidates.prototype_plan(analysis, case, record['proposal'])
    record.update(timeline_digest=candidates.timeline_digest(plan), status='needs_review')
    record['review']['joins'] = authored_join_rows(case, plan, 2)
    row, = record['review']['joins']
    row['change']['kind'] = 'physical_event'
    row['change']['before']['state'] = 'The girl is standing.'
    row['change']['after']['state'] = 'The girl has fallen.'
    if boundary_neighbor:
        row['change']['after']['frame'] = max(
            (frame for frame in case['frames'] if frame['time'] < 39.), key=lambda frame: frame['time'])['index']
    record['review']['boundaries'] = [{'cut': i, 'side': side, 'safe': True,
        'frames': [candidates.boundary_anchor(case, cut, side)], 'evidence': 'AUTHORED retained edge.'}
        for i, cut in enumerate(plan['parts'][0]['cuts'], 1) for side in ('start', 'end')]
    return analysis, record, plan


class StoryCandidateContractTests(unittest.TestCase):
    def status(self, analysis, record, plan):
        return candidates.review_status(analysis, record['case'], record['proposal'], plan, record['review'])

    def test_catalog_preserves_utterances_despite_internal_shot_edges(self):
        analysis = source_fixture()
        catalog = candidates.source_catalog(analysis, SOURCE_SHA)
        self.assertEqual([(row['start'], row['end']) for row in catalog], [(0., 20.), (20., 40.), (40., 60.)])
        self.assertEqual([row['text'] for row in catalog], [row['text'] for row in analysis['transcript']['segments']])
        self.assertEqual(catalog[0]['shot_ids'], ['s0', 's1'])
        self.assertNotEqual(catalog[0]['id'], candidates.source_catalog(analysis, 'c' * 64)[0]['id'])

    def test_source_join_describes_actual_audible_gap_and_owned_observations_without_mutation(self):
        analysis, record, plan = source_join_fixture()
        before = copy.deepcopy((analysis, record, plan))
        case = record['case']
        left, right = plan['parts'][0]['cuts']
        join, = candidates.source_joins(case, plan)
        self.assertEqual(join, {'after_cut': 1, 'start': left['end'], 'end': right['start'],
            'left_frame': candidates.boundary_anchor(case, left, 'end'),
            'right_frame': candidates.boundary_anchor(case, right, 'start'),
            'omitted_frames': [frame['index'] for frame in case['frames']
                if left['end'] <= frame['time'] < right['start']],
            'unit_ids': [unit['id'] for unit in case['units']
                if unit['start'] < right['start'] and left['end'] < unit['end']]})
        self.assertNotEqual(join['end'], plan['semantic_ranges'][1]['start'])
        self.assertEqual((analysis, record, plan), before)
        self.assertEqual(self.status(analysis, record, plan), 'ready')

    def test_source_join_policy_reaches_scoped_compiler_and_cannot_be_dropped_on_one_side(self):
        analysis, record, plan = source_join_fixture()
        _, scoped = candidates.prototype_plan(analysis, record['case'], record['proposal'])
        self.assertEqual(scoped['source_join_policy'], candidates.SOURCE_JOIN_POLICY)
        self.assertIsNot(scoped['source_join_policy'], analysis['source_join_policy'])
        scoped['candidate_evidence'] = copy.deepcopy(record)
        self.assertEqual(candidates.inspect_candidate_quality(scoped, plan)['status'], 'passed')
        analysis['candidate_records'] = [record]
        self.assertEqual(len(candidates.compile_candidates(analysis, None)['candidates']), 1)
        for side in ('analysis', 'case'):
            invalid_analysis, invalid_record = copy.deepcopy((analysis, record))
            target = invalid_analysis if side == 'analysis' else invalid_record['case']
            target.pop('source_join_policy')
            with self.subTest(side=side), self.assertRaisesRegex(ValueError, 'source join policy'):
                self.status(invalid_analysis, invalid_record, plan)
            invalid_analysis['candidate_records'] = [invalid_record]
            self.assertEqual(candidates.compile_candidates(invalid_analysis, None)['candidates'], [])

    def test_source_join_policy_requires_exact_supported_version(self):
        for policy in ({}, {'version': 3}, {'version': True}, {'version': 1, 'extra': True}):
            analysis, record, plan = source_join_fixture()
            analysis['source_join_policy'] = policy
            record['case']['source_join_policy'] = copy.deepcopy(policy)
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError, 'source join policy'):
                self.status(analysis, record, plan)

    def test_discovery_cases_copy_join_policy_from_new_analysis(self):
        analysis = source_fixture()
        analysis['source_join_policy'] = copy.deepcopy(candidates.SOURCE_JOIN_POLICY)
        episode_map = {'source_sha256': SOURCE_SHA, 'authority': 'hypothesis_only',
            'windows': [{'id': 'w', 'start': 0., 'end': 60.}],
            'hypotheses': [{'id': 'h', 'window_ids': ['w'], 'prerequisite_window_ids': []}]}
        case, = candidates.candidate_cases(analysis, episode_map, SOURCE_SHA)
        self.assertEqual(case['source_join_policy'], candidates.SOURCE_JOIN_POLICY)
        self.assertIsNot(case['source_join_policy'], analysis['source_join_policy'])
        candidates.validate_case(analysis, case)

    def test_legacy_join_free_review_remains_readable_but_new_policy_requires_field_and_coverage(self):
        analysis, record, plan = establishing_reaction_fixture(multiple_cuts=True)
        self.assertNotIn('joins', candidates.review_schema(record['case'], record['proposal'], plan)['properties'])
        self.assertEqual(self.status(analysis, record, plan), 'ready')
        analysis, record, plan = source_join_fixture(version=1)
        join_schema = candidates.review_schema(record['case'], record['proposal'], plan)['properties']['joins']
        self.assertNotIn('change', join_schema['items']['oneOf'][0]['properties'])
        self.assertEqual(self.status(analysis, record, plan), 'ready')
        for mode in ('missing_field', 'missing_join', 'duplicate_join'):
            analysis, record, plan = source_join_fixture()
            if mode == 'missing_field':
                record['review'].pop('joins')
            elif mode == 'missing_join':
                record['review']['joins'] = []
            else:
                record['review']['joins'].append(copy.deepcopy(record['review']['joins'][0]))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.status(analysis, record, plan)

    def test_source_join_approval_rejects_foreign_edges_retained_or_foreign_gap_images(self):
        for mode in ('left_edge', 'right_edge', 'retained_middle', 'no_omitted', 'foreign_gap', 'blank_evidence'):
            analysis, record, plan = source_join_fixture()
            row = record['review']['joins'][0]
            if mode == 'left_edge':
                row['frames'][0] = record['case']['frames'][0]['index']
            elif mode == 'right_edge':
                row['frames'][-1] = record['case']['frames'][-1]['index']
            elif mode == 'retained_middle':
                row['frames'][1] = record['case']['frames'][0]['index']
            elif mode == 'no_omitted':
                row['frames'] = [row['frames'][0], row['frames'][-1]]
            elif mode == 'foreign_gap':
                # A real observed image outside this join is not omitted evidence.
                row['frames'][1] = next(frame['index'] for frame in record['case']['frames']
                                         if frame['time'] > plan['parts'][0]['cuts'][1]['start']+1)
            else:
                row['evidence'] = ' '
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.status(analysis, record, plan)

    def test_source_join_unsafe_causal_or_uncertain_decisions_cannot_approve(self):
        for safe, classification in ((False, 'incidental'), (True, 'required_cause'),
                (True, 'required_response'), (True, 'required_action'), (True, 'unresolved'),
                (False, 'required_action')):
            analysis, record, plan = source_join_fixture()
            record['review']['joins'][0].update(safe_to_omit=safe, classification=classification)
            with self.subTest(safe=safe, classification=classification):
                self.assertEqual(self.status(analysis, record, plan), 'needs_review')

    def test_negative_join_review_needs_no_fabricated_join_or_story_proof(self):
        for decision, status in (({'resolved': False}, 'needs_review'), ({'is_story': False}, 'declined'),
                                 ({'issues': ['The omitted fall is required.']}, 'needs_review')):
            analysis, record, plan = source_join_fixture()
            record['review'].update(decision, joins=[], proofs=[], dialogue=[], boundaries=[])
            before = copy.deepcopy(record)
            with self.subTest(decision=decision):
                self.assertEqual(self.status(analysis, record, plan), status)
                self.assertEqual(record, before)

    def test_source_join_cannot_approve_unobserved_gap_and_single_cut_needs_no_join(self):
        analysis, record, plan = source_join_fixture()
        join, = candidates.source_joins(record['case'], plan)
        record['case']['frames'] = [frame for frame in record['case']['frames']
                                   if frame['index'] not in join['omitted_frames']]
        self.assertEqual(candidates.source_joins(record['case'], plan)[0]['omitted_frames'], [])
        record['review']['joins'] = []
        with self.assertRaisesRegex(ValueError, 'source gap'):
            self.status(analysis, record, plan)
        record['review']['resolved'] = False
        self.assertEqual(self.status(analysis, record, plan), 'needs_review')
        analysis, record, plan = source_join_fixture(multiple_cuts=False)
        self.assertEqual(candidates.source_joins(record['case'], plan), [])
        self.assertEqual(record['review']['joins'], [])
        self.assertEqual(self.status(analysis, record, plan), 'ready')

    def test_changed_actual_geometry_rebinds_gap_images_and_retained_anchors(self):
        analysis, record, plan = source_join_fixture()
        prior, = candidates.source_joins(record['case'], plan)
        changed = copy.deepcopy(plan)
        changed['parts'][0]['cuts'][0]['end'] = 30.1
        current, = candidates.source_joins(record['case'], changed)
        self.assertNotEqual(prior['left_frame'], current['left_frame'])
        self.assertNotEqual(prior['omitted_frames'], current['omitted_frames'])
        with self.assertRaises(ValueError):
            self.status(analysis, record, changed)

    def test_multiple_source_joins_require_separate_owned_omitted_images(self):
        analysis, record, _ = source_join_fixture()
        case = record['case']
        silent = next(unit for unit in case['units'] if unit['start'] == 15.)
        index = max(frame['index'] for frame in case['frames'])+1
        case['frames'].append({'index': index, 'unit': silent['id'], 'time': 17.,
            'sha256': f'{index:064x}', 'path': str(ROOT/'temp'/f'authored-mechanism-frame-{index}.jpg')})
        case['frames'].append({'index': index+1, 'unit': silent['id'], 'time': 18.,
            'sha256': f'{index+1:064x}', 'path': str(ROOT/'temp'/f'authored-mechanism-frame-{index+1}.jpg')})
        spans = ((0., 15.), (20., 30.), (40., 60.))
        record['proposal']['cuts'] = [{
            'first': next(unit['id'] for unit in case['units'] if unit['start'] == a),
            'last': next(unit['id'] for unit in case['units'] if unit['end'] == b)} for a, b in spans]
        plan, _ = candidates.prototype_plan(analysis, case, record['proposal'])
        joins = candidates.source_joins(case, plan)
        self.assertEqual([join['after_cut'] for join in joins], [1, 2])
        self.assertTrue(all(join['omitted_frames'] for join in joins))
        record['review']['joins'] = authored_join_rows(case, plan, 2)
        record['review']['boundaries'] = [{'cut': i, 'side': side, 'safe': True,
            'frames': [candidates.boundary_anchor(case, cut, side)],
            'evidence': 'AUTHORED original retained edge check.'}
            for i, cut in enumerate(plan['parts'][0]['cuts'], 1) for side in ('start', 'end')]
        self.assertEqual(self.status(analysis, record, plan), 'ready')
        original = copy.deepcopy(record['review']['joins'])
        record['review']['joins'].pop()
        with self.assertRaisesRegex(ValueError, 'source gap'):
            self.status(analysis, record, plan)
        record['review']['joins'] = original
        record['review']['joins'][1]['frames'][1] = joins[0]['omitted_frames'][0]
        with self.assertRaises(ValueError):
            self.status(analysis, record, plan)

    def test_v2_omitted_physical_event_cannot_be_waived_as_incidental_or_inferable(self):
        for kind in ('physical_event', 'object_change', 'reveal', 'scene_change'):
            analysis, record, plan = source_join_fixture()
            row = record['review']['joins'][0]
            row['change']['kind'] = kind
            row['change']['before']['state'] = 'The girl is standing.'
            row['change']['after']['state'] = 'The girl has fallen onto the floor.'
            row['evidence'] = 'The fall is omitted, but the kept pain lets a viewer infer what happened.'
            self.assertTrue(row['safe_to_omit'])
            self.assertEqual(row['classification'], 'incidental')
            self.assertTrue(all(record['review']['criteria'].values()))
            with self.subTest(kind=kind):
                self.assertEqual(self.status(analysis, record, plan), 'needs_review')
        # Earlier approved decisions keep their versioned meaning; no invented
        # factual approval is added while reading an old answer.
        analysis, record, plan = source_join_fixture(version=1)
        record['review']['joins'][0]['evidence'] = 'The omitted action can be inferred from retained aftermath.'
        self.assertEqual(self.status(analysis, record, plan), 'ready')

    def test_v2_incidental_waiting_minor_motion_and_speech_do_not_require_keep_all(self):
        for kind in ('none', 'minor_motion', 'speech_only'):
            analysis, record, plan = source_join_fixture()
            record['review']['joins'][0]['change']['kind'] = kind
            with self.subTest(kind=kind):
                self.assertEqual(self.status(analysis, record, plan), 'ready')

    def test_v2_requires_its_factual_fields_without_backfilling_v1(self):
        for missing in ('change', 'retained_witness'):
            analysis, record, plan = source_join_fixture()
            record['review']['joins'][0].pop(missing)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                self.status(analysis, record, plan)

    def test_v2_change_observations_need_owned_cited_omitted_images(self):
        for mode in ('retained_before', 'foreign_after', 'uncited_before'):
            analysis, record, plan = source_join_fixture()
            row = record['review']['joins'][0]
            if mode == 'retained_before':
                row['change']['before']['frame'] = row['frames'][0]
            elif mode == 'foreign_after':
                row['change']['after']['frame'] = max(frame['index'] for frame in record['case']['frames'])+1
            else:
                row['frames'].remove(row['change']['before']['frame'])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.status(analysis, record, plan)

    def test_v2_missing_temporal_or_pixel_evidence_is_unresolved_not_approved(self):
        for mode in ('same_frame', 'reversed', 'empty_state', 'unresolved'):
            analysis, record, plan = source_join_fixture()
            row = record['review']['joins'][0]
            before, after = row['change']['before'], row['change']['after']
            if mode == 'same_frame':
                after['frame'] = before['frame']
            elif mode == 'reversed':
                before['frame'], after['frame'] = after['frame'], before['frame']
            elif mode == 'empty_state':
                before['state'] = ' '
            else:
                row['change']['kind'] = 'unresolved'
            with self.subTest(mode=mode):
                self.assertEqual(self.status(analysis, record, plan), 'needs_review')

    def test_v2_identical_pixels_can_prove_unchanged_waiting_but_not_motion_or_events(self):
        for kind in ('none', 'speech_only', 'minor_motion', 'physical_event', 'object_change', 'reveal', 'scene_change'):
            analysis, record, plan = source_join_fixture()
            row = record['review']['joins'][0]
            row['change']['kind'] = kind
            before, after = row['change']['before'], row['change']['after']
            frames = {frame['index']: frame for frame in record['case']['frames']}
            self.assertNotEqual(before['frame'], after['frame'])
            self.assertLess(frames[before['frame']]['time'], frames[after['frame']]['time'])
            frames[after['frame']]['sha256'] = frames[before['frame']]['sha256']
            if kind not in ('none', 'speech_only'):
                after['state'] = 'A claimed visible change unsupported by identical pixels.'
                cut = plan['parts'][0]['cuts'][0]
                row['retained_witness'] = {'frames': [frame['index'] for frame in record['case']['frames']
                    if cut['start'] <= frame['time'] < cut['end']][-2:],
                    'evidence': 'AUTHORED kept pair cannot repair absent original change evidence.'}
            with self.subTest(kind=kind):
                self.assertEqual(self.status(analysis, record, plan),
                    'ready' if kind in ('none', 'speech_only') else 'needs_review')

    def test_v2_single_observed_gap_image_cannot_establish_unchanged_state(self):
        analysis, record, plan = source_join_fixture()
        row = record['review']['joins'][0]
        first, second = row['change']['before']['frame'], row['change']['after']['frame']
        record['case']['frames'] = [frame for frame in record['case']['frames'] if frame['index'] != second]
        row['frames'].remove(second)
        row['change']['after']['frame'] = first
        self.assertEqual(self.status(analysis, record, plan), 'needs_review')

    def test_v2_substantive_event_requires_continuous_retained_witness_not_join_edges(self):
        for mode in ('valid', 'join_edges', 'one_frame', 'empty_evidence', 'reversed', 'identical_pixels',
                     'omitted_image', 'same_states'):
            analysis, record, plan = source_join_fixture()
            row = record['review']['joins'][0]
            row['change']['kind'] = 'physical_event'
            row['change']['before']['state'] = 'The girl is standing.'
            row['change']['after']['state'] = 'The girl has fallen.'
            cut = plan['parts'][0]['cuts'][0]
            kept = [frame['index'] for frame in record['case']['frames']
                    if cut['start'] <= frame['time'] < cut['end']][-2:]
            row['retained_witness'] = {'frames': kept, 'evidence':
                'AUTHORED mechanism fixture: the same complete fall is observed within this continuous cut.'}
            witness = row['retained_witness']
            if mode == 'join_edges':
                witness['frames'] = [row['frames'][0], row['frames'][-1]]
            elif mode == 'one_frame':
                witness['frames'] = kept[:1]
            elif mode == 'empty_evidence':
                witness['evidence'] = ' '
            elif mode == 'reversed':
                witness['frames'] = kept[::-1]
            elif mode == 'identical_pixels':
                frames = {frame['index']: frame for frame in record['case']['frames']}
                frames[kept[1]]['sha256'] = frames[kept[0]]['sha256']
            elif mode == 'omitted_image':
                witness['frames'] = [row['change']['before']['frame'], row['change']['after']['frame']]
            elif mode == 'same_states':
                row['change']['after']['state'] = row['change']['before']['state']
            with self.subTest(mode=mode):
                if mode == 'omitted_image':
                    with self.assertRaises(ValueError):
                        self.status(analysis, record, plan)
                else:
                    self.assertEqual(self.status(analysis, record, plan), 'ready' if mode == 'valid' else 'needs_review')

    def test_source_restoration_adds_entire_grounded_catalog_run_without_approving_or_mutating(self):
        analysis, record, plan = source_restoration_fixture()
        self.assertEqual(self.status(analysis, record, plan), 'needs_review')
        row, = record['review']['joins']
        self.assertTrue(row['safe_to_omit'])
        self.assertEqual(row['classification'], 'incidental')
        self.assertEqual(record['review']['required_units'], [])
        before = copy.deepcopy((analysis, record, plan))
        changed = candidates.proposal_from_source_joins(analysis, record['case'], record['proposal'], plan, record)
        self.assertIsNotNone(changed)
        self.assertEqual(candidates.proposal_ranges(record['case'], changed), [{'start': 0., 'end': 60.}])
        restored = candidates.selected_units(record['case'], changed)
        middle = next(unit for unit in record['case']['units'] if unit['start'] == 33.)
        self.assertIn(middle, restored)
        self.assertEqual({key: value for key, value in changed.items() if key != 'cuts'},
                         {key: value for key, value in record['proposal'].items() if key != 'cuts'})
        self.assertNotIn('export_eligible', changed)
        self.assertEqual((analysis, record, plan), before)
        self.assertIsNot(changed, record['proposal'])
        # A catalog unit can straddle an audible handle: only the caller's
        # rebuilt audible-delta check can establish the actual changed footage.
        join, = candidates.source_joins(record['case'], plan)
        self.assertGreater(middle['start'], join['start'])
        after = next(frame for frame in record['case']['frames'] if frame['index'] == row['change']['after']['frame'])
        owner = next(unit for unit in record['case']['units'] if unit['id'] == after['unit'])
        self.assertGreater(owner['end'], join['end'])

    def test_source_restoration_closes_immediate_owner_of_old_right_audible_handle(self):
        analysis, record, plan = source_restoration_fixture(boundary_neighbor=True)
        case = record['case']
        row, = record['review']['joins']
        frames = {frame['index']: frame for frame in case['frames']}
        after = next(unit for unit in case['units'] if unit['id'] == frames[row['change']['after']['frame']]['unit'])
        neighbor = next(unit for unit in case['units'] if unit['start'] == after['end'])
        join, = candidates.source_joins(case, plan)
        self.assertEqual((after['end'], neighbor['start'], neighbor['end']), (39., 39., 40.))
        self.assertLess(neighbor['start'], join['end'])
        self.assertLess(join['end'], neighbor['end'])
        before = copy.deepcopy((analysis, record, plan))
        changed = candidates.proposal_from_source_joins(analysis, case, record['proposal'], plan, record)
        self.assertIsNotNone(changed)
        self.assertIn(neighbor, candidates.selected_units(case, changed))
        self.assertEqual(candidates.proposal_ranges(case, changed), [{'start': 0., 'end': 60.}])
        rebuilt, _ = candidates.prototype_plan(analysis, case, changed)
        from app.source_ranges import subtract_ranges
        self.assertEqual(subtract_ranges(plan['parts'][0]['cuts'], rebuilt['parts'][0]['cuts']), [])
        self.assertEqual((analysis, record, plan), before)

    def test_source_restoration_closes_only_immediate_owners_of_both_old_audible_edges(self):
        analysis, record, _ = source_restoration_fixture(boundary_neighbor=True)
        case = record['case']
        first = record['proposal']['cuts'][0]
        first['last'] = next(unit['id'] for unit in case['units'] if unit['end'] == 25.)
        plan, _ = candidates.prototype_plan(analysis, case, record['proposal'])
        record['timeline_digest'] = candidates.timeline_digest(plan)
        record['review']['joins'] = authored_join_rows(case, plan, 2)
        row, = record['review']['joins']
        row['change'] = {'kind': 'physical_event',
            'before': {'frame': next(frame['index'] for frame in case['frames'] if frame['time'] == 30.04),
                       'state': 'The girl is standing.'},
            'after': {'frame': next(frame['index'] for frame in case['frames'] if frame['time'] == 38.96),
                      'state': 'The girl has fallen.'}}
        record['review']['boundaries'] = [{'cut': i, 'side': side, 'safe': True,
            'frames': [candidates.boundary_anchor(case, cut, side)], 'evidence': 'AUTHORED retained edge.'}
            for i, cut in enumerate(plan['parts'][0]['cuts'], 1) for side in ('start', 'end')]
        self.assertAlmostEqual(plan['parts'][0]['cuts'][0]['end'], 25.55)
        changed = candidates.proposal_from_source_joins(analysis, case, record['proposal'], plan, record)
        self.assertIsNotNone(changed)
        self.assertEqual(candidates.proposal_ranges(case, changed), [{'start': 0., 'end': 60.}])

    def test_source_restoration_does_not_walk_through_units_towards_a_distant_audible_edge(self):
        analysis, record, plan = source_restoration_fixture(boundary_neighbor=True)
        case = record['case']
        row, = record['review']['joins']
        row['change']['after']['frame'] = next(frame['index'] for frame in case['frames'] if frame['time'] == 35.96)
        changed = candidates.proposal_from_source_joins(analysis, case, record['proposal'], plan, record)
        self.assertIsNotNone(changed)
        self.assertEqual(candidates.proposal_ranges(case, changed),
                         [{'start': 0., 'end': 36.}, {'start': 40., 'end': 60.}])
        # The edge owner is now immediate only in list position, not in source
        # time. A missing catalog interval cannot become a restoration bridge.
        missing = next(unit for unit in case['units'] if unit['start'] == 36.)
        removed = {frame['index'] for frame in case['frames'] if frame['unit'] == missing['id']}
        case['units'].remove(missing)
        case['frames'] = [frame for frame in case['frames'] if frame['index'] not in removed]
        row['frames'] = [index for index in row['frames'] if index not in removed]
        from app.source_ranges import merge_ranges
        case['source_ranges'] = merge_ranges(case['units'])
        candidates.validate_case(analysis, case)
        self.assertIsNone(candidates.proposal_from_source_joins(analysis, case, record['proposal'], plan, record))

    def test_source_restoration_rejects_stale_timeline_or_foreign_source_binding(self):
        for mode in ('record_digest', 'plan_geometry', 'plan_source', 'analysis_source', 'bound_case_source',
                     'bound_case_pixels', 'case_pixels'):
            analysis, record, plan = source_restoration_fixture()
            case = record['case']
            if mode == 'record_digest':
                record['timeline_digest'] = 'f'*64
            elif mode == 'plan_geometry':
                plan['parts'][0]['cuts'][0]['end'] += .1
            elif mode == 'plan_source':
                plan['source']['sha256'] = 'f'*64
            elif mode == 'analysis_source':
                analysis['source_sha256'] = 'f'*64
            elif mode == 'bound_case_source':
                record['case'] = copy.deepcopy(case)
                record['case']['source_sha256'] = 'f'*64
            elif mode == 'bound_case_pixels':
                record['case'] = copy.deepcopy(case)
                record['case']['frames'][0]['sha256'] = 'f'*64
            else:
                case = copy.deepcopy(case)
                case['frames'][0]['sha256'] = 'f'*64
            with self.subTest(mode=mode):
                self.assertIsNone(candidates.proposal_from_source_joins(analysis, case, record['proposal'], plan, record))

    def test_source_restoration_independently_rejects_invalid_negative_join_proofs(self):
        for mode in ('retained_pair', 'foreign_pair', 'uncited_pair', 'reversed_pair', 'same_pair',
                     'identical_pixels', 'empty_state', 'same_states', 'wrong_anchor', 'unordered_citations',
                     'empty_evidence', 'duplicate_join'):
            analysis, record, plan = source_restoration_fixture()
            # Negative source decisions return before approval-proof validation;
            # a restoration must still establish all facts it proposes to keep.
            record['review']['issues'] = ['The source event is absent from the edit.']
            row, = record['review']['joins']
            pair = row['change']
            if mode == 'retained_pair':
                pair['before']['frame'] = row['frames'][0]
            elif mode == 'foreign_pair':
                pair['after']['frame'] = max(frame['index'] for frame in record['case']['frames'])+1
            elif mode == 'uncited_pair':
                row['frames'].remove(pair['before']['frame'])
            elif mode == 'reversed_pair':
                pair['before'], pair['after'] = pair['after'], pair['before']
            elif mode == 'same_pair':
                pair['after']['frame'] = pair['before']['frame']
            elif mode == 'identical_pixels':
                frames = {frame['index']: frame for frame in record['case']['frames']}
                frames[pair['after']['frame']]['sha256'] = frames[pair['before']['frame']]['sha256']
            elif mode == 'empty_state':
                pair['before']['state'] = ' '
            elif mode == 'same_states':
                pair['after']['state'] = pair['before']['state']
            elif mode == 'wrong_anchor':
                row['frames'][-1] = record['case']['frames'][-1]['index']
            elif mode == 'unordered_citations':
                row['frames'][1:3] = row['frames'][1:3][::-1]
            elif mode == 'empty_evidence':
                row['evidence'] = ' '
            else:
                record['review']['joins'].append(copy.deepcopy(row))
            with self.subTest(mode=mode):
                self.assertIsNone(candidates.proposal_from_source_joins(
                    analysis, record['case'], record['proposal'], plan, record))

    def test_source_restoration_never_expands_unknown_static_or_unblocked_motion(self):
        for kind, safe, classification, expected in (
                ('none', False, 'required_action', False), ('speech_only', False, 'required_response', False),
                ('unresolved', False, 'required_action', False), ('minor_motion', True, 'incidental', False),
                ('minor_motion', False, 'incidental', False), ('minor_motion', True, 'required_action', False),
                ('minor_motion', False, 'required_response', True)):
            analysis, record, plan = source_restoration_fixture()
            row, = record['review']['joins']
            row.update(safe_to_omit=safe, classification=classification)
            row['change']['kind'] = kind
            with self.subTest(kind=kind, safe=safe, classification=classification):
                result = candidates.proposal_from_source_joins(analysis, record['case'], record['proposal'], plan, record)
                self.assertEqual(result is not None, expected)

    def test_source_restoration_never_retries_or_uses_unresolved_or_already_witnessed_records(self):
        for mode in ('repair_attempt', 'qualification_history', 'original_proposal', 'wrong_status',
                     'unresolved', 'not_story', 'requested', 'v1', 'already_witnessed'):
            analysis, record, plan = source_restoration_fixture()
            if mode in ('repair_attempt', 'qualification_history', 'original_proposal'):
                record[mode] = {}
            elif mode == 'wrong_status':
                record['status'] = 'ready'
            elif mode == 'unresolved':
                record['review']['resolved'] = False
            elif mode == 'not_story':
                record['review']['is_story'] = False
            elif mode == 'requested':
                record['review']['requested_units'] = [record['case']['units'][0]['id']]
            elif mode == 'v1':
                analysis['source_join_policy'] = record['case']['source_join_policy'] = {'version': 1}
            else:
                row, = record['review']['joins']
                cut = plan['parts'][0]['cuts'][0]
                row['retained_witness'] = {'frames': [frame['index'] for frame in record['case']['frames']
                    if cut['start'] <= frame['time'] < cut['end']][-2:],
                    'evidence': 'AUTHORED same event is already kept continuously.'}
                record['review']['issues'] = ['An unrelated pacing problem still needs review.']
            with self.subTest(mode=mode):
                self.assertIsNone(candidates.proposal_from_source_joins(
                    analysis, record['case'], record['proposal'], plan, record))

    def test_source_restoration_cannot_bridge_a_missing_catalog_interval(self):
        analysis, record, plan = source_restoration_fixture()
        case = record['case']
        missing = next(unit for unit in case['units'] if unit['start'] == 33.)
        removed = {frame['index'] for frame in case['frames'] if frame['unit'] == missing['id']}
        case['units'].remove(missing)
        case['frames'] = [frame for frame in case['frames'] if frame['index'] not in removed]
        from app.source_ranges import merge_ranges
        case['source_ranges'] = merge_ranges(case['units'])
        record['review']['joins'][0]['frames'] = [index for index in record['review']['joins'][0]['frames']
                                                if index not in removed]
        candidates.validate_case(analysis, case)
        self.assertIsNone(candidates.proposal_from_source_joins(analysis, case, record['proposal'], plan, record))

    def test_source_restoration_keeps_other_gaps_and_restores_only_the_grounded_run(self):
        analysis, record, _ = source_restoration_fixture()
        case = record['case']
        spans = ((0., 15.), (20., 30.), (40., 60.))
        record['proposal']['cuts'] = [{
            'first': next(unit['id'] for unit in case['units'] if unit['start'] == a),
            'last': next(unit['id'] for unit in case['units'] if unit['end'] == b)} for a, b in spans]
        plan, _ = candidates.prototype_plan(analysis, case, record['proposal'])
        record['timeline_digest'] = candidates.timeline_digest(plan)
        record['review']['joins'] = authored_join_rows(case, plan, 2)
        row = record['review']['joins'][-1]
        row['change']['kind'] = 'physical_event'
        row['change']['before']['state'] = 'The girl is standing.'
        row['change']['after']['state'] = 'The girl has fallen.'
        record['review']['boundaries'] = [{'cut': i, 'side': side, 'safe': True,
            'frames': [candidates.boundary_anchor(case, cut, side)], 'evidence': 'AUTHORED retained edge.'}
            for i, cut in enumerate(plan['parts'][0]['cuts'], 1) for side in ('start', 'end')]
        changed = candidates.proposal_from_source_joins(analysis, case, record['proposal'], plan, record)
        self.assertIsNotNone(changed)
        self.assertEqual(candidates.proposal_ranges(case, changed),
                         [{'start': 0., 'end': 15.}, {'start': 20., 'end': 60.}])

    def test_catalog_unites_word_crossing_utterance_edge(self):
        analysis = source_fixture()
        analysis['transcript']['words'] = [
            {'start': 1., 'end': 2., 'text': 'First'},
            {'start': 19.5, 'end': 20.5, 'text': 'crossing'},
            {'start': 41., 'end': 42., 'text': 'Last'},
        ]
        catalog = candidates.source_catalog(analysis, SOURCE_SHA)
        self.assertEqual([(row['start'], row['end']) for row in catalog], [(0., 40.), (40., 60.)])
        self.assertEqual(catalog[0]['text'], 'First crossing')

    def test_catalog_clamps_millisecond_shot_rounding_without_rewriting_source(self):
        analysis = source_fixture()
        duration = 120.036583
        analysis['probe']['duration'] = duration
        analysis['shots'].append({'id': 'last', 'start': 60., 'end': 120.037})
        before = copy.deepcopy(analysis)
        catalog = candidates.source_catalog(analysis, SOURCE_SHA)
        self.assertEqual(catalog[-1]['end'], duration)
        self.assertEqual(catalog[-1]['shot_ids'], ['last'])
        self.assertTrue(all(unit['end'] <= duration for unit in catalog))
        self.assertEqual(analysis, before)
        analysis['shots'][-1]['end'] = duration + .01
        with self.assertRaisesRegex(ValueError, 'Invalid source shot'):
            candidates.source_catalog(analysis, SOURCE_SHA)

    def test_cut_context_adds_original_handle_units_without_changing_selection_or_approval(self):
        analysis, case, proposal = edge_utterance_fixture()
        before = copy.deepcopy((analysis, case, proposal))
        selected = candidates.selected_units(case, proposal)
        with self.assertRaisesRegex(ValueError, 'Audio handles leave'):
            candidates.prototype_plan(analysis, case, proposal)
        expanded = candidates.with_cut_context(analysis, case, proposal)
        candidates.validate_case(analysis, expanded)
        self.assertEqual((analysis, case, proposal), before)
        self.assertEqual(candidates.selected_units(expanded, proposal), selected)
        self.assertGreater(len(expanded['units']), len(case['units']))
        self.assertEqual(expanded['source_ranges'], [{'start': 0., 'end': 60.}])
        self.assertEqual(expanded['hypothesis'], case['hypothesis'])
        self.assertEqual(expanded['frames'], [])
        plan, scoped = candidates.prototype_plan(analysis, expanded, proposal)
        self.assertEqual(plan['semantic_ranges'], [{'start': 20., 'end': 40.}])
        cut = plan['parts'][0]['cuts'][0]
        self.assertAlmostEqual(cut['start'], 19.82)
        self.assertAlmostEqual(cut['end'], 40.55)
        context = [event for event in scoped['events'] if event['id'] != selected[0]['id']]
        self.assertTrue(context)
        self.assertTrue(all(event['selected_ranges'] == [] for event in context))
        self.assertNotIn('export_eligible', plan)
        self.assertEqual(candidates.inspect_candidate_quality(scoped, plan)['status'], 'unresolved')

    def test_draft_expands_handle_context_but_preserves_core_and_nonexportable_status(self):
        analysis, case, proposal = edge_utterance_fixture()
        before = copy.deepcopy((analysis, case, proposal))
        draft, scoped = candidates.prototype_plan(analysis, case, proposal, draft=True)
        self.assertEqual((analysis, case, proposal), before)
        self.assertEqual(draft['semantic_ranges'], [{'start': 20., 'end': 40.}])
        self.assertAlmostEqual(draft['parts'][0]['cuts'][0]['start'], 19.82)
        self.assertAlmostEqual(draft['parts'][0]['cuts'][0]['end'], 40.55)
        self.assertTrue(draft['draft'])
        self.assertFalse(draft['export_eligible'])
        self.assertEqual(draft['editorial_status'], 'not_approved')
        from app.planner import validate_plan
        validate_plan(draft, scoped, allow_draft=True)
        with self.assertRaises(ValueError):
            validate_plan(draft, scoped)

    def test_hypothesis_window_selects_whole_overlapping_utterance(self):
        analysis = source_fixture()
        episode_map = {'source_sha256': SOURCE_SHA, 'authority': 'hypothesis_only',
                       'windows': [{'id': 'w', 'start': 5., 'end': 25.}],
                       'hypotheses': [{'id': 'h', 'window_ids': ['w'], 'prerequisite_window_ids': []}]}
        case = candidates.candidate_cases(analysis, episode_map, SOURCE_SHA)[0]
        self.assertEqual(case['source_ranges'], [{'start': 0., 'end': 40.}])
        self.assertEqual(len(case['units']), 2)
        episode_map['source_sha256'] = 'c' * 64
        with self.assertRaises(ValueError):
            candidates.candidate_cases(analysis, episode_map, SOURCE_SHA)

    def test_disconnected_context_allows_separate_cuts_but_not_unobserved_bridge(self):
        _, record, _ = candidate_fixture()
        case, proposal = record['case'], record['proposal']
        case['units'].pop(1)
        first, last = case['units']
        proposal['cuts'] = [{'first': first['id'], 'last': last['id']}]
        with self.assertRaisesRegex(ValueError, 'unobserved'):
            candidates.proposal_ranges(case, proposal)
        proposal['cuts'] = [{'first': unit['id'], 'last': unit['id']} for unit in (first, last)]
        self.assertEqual(candidates.proposal_ranges(case, proposal),
                         [{'start': 0., 'end': 20.}, {'start': 40., 'end': 60.}])

    def test_cut_order_or_overlap_cannot_replay_source(self):
        _, record, _ = candidate_fixture()
        case, proposal = record['case'], record['proposal']
        first, middle, last = case['units']
        for cuts in (
            [{'first': last['id'], 'last': first['id']}],
            [{'first': middle['id'], 'last': last['id']}, {'first': first['id'], 'last': first['id']}],
            [{'first': first['id'], 'last': middle['id']}, {'first': middle['id'], 'last': last['id']}],
        ):
            with self.subTest(cuts=cuts), self.assertRaises(ValueError):
                candidates.proposal_ranges(case, {**proposal, 'cuts': cuts})

    def test_ready_review_rechecks_complete_source_and_compiles_without_mutation(self):
        analysis, record, plan = candidate_fixture()
        analysis['candidate_records'] = [record]
        before = copy.deepcopy(analysis)
        self.assertEqual(self.status(analysis, record, plan), 'ready')
        result = candidates.compile_candidates(analysis, None)
        self.assertEqual(len(result['candidates']), 1, result['declined'])
        candidate = result['candidates'][0]
        self.assertTrue(candidate['export_eligible'])
        self.assertEqual(candidates.inspect_candidate_quality(candidate['scoped_analysis'], candidate['plan'])['status'], 'passed')
        self.assertEqual(analysis, before)

    def test_incomplete_native_verdict_is_reusable_but_never_ready(self):
        for change, expected in (({'resolved': False}, 'needs_review'), ({'is_story': False}, 'declined'),
                                 ({'issues': ['The source ending is incomplete.']}, 'needs_review')):
            analysis, record, plan = candidate_fixture()
            record['review'].update(change)
            with self.subTest(change=change):
                self.assertEqual(self.status(analysis, record, plan), expected)
                analysis['candidate_records'] = [record]
                result = candidates.compile_candidates(analysis, None)
                self.assertEqual(result['candidates'], [])
                self.assertTrue(all(not row['export_eligible'] for row in result['drafts']))

    def test_contextual_native_approval_cannot_upgrade_missing_negative_or_tampered_cut_only_screen(self):
        for failure in ('missing', 'unresolved', 'not_story', 'criterion', 'issues',
                        'binding', 'source', 'image', 'forged_quote'):
            analysis, record, plan = candidate_fixture()
            if failure == 'missing':
                record.pop('screen')
            elif failure == 'unresolved':
                record['screen']['verdict'].update(resolved=False, proofs=[])
            elif failure == 'not_story':
                record['screen']['verdict'].update(is_story=False, proofs=[])
            elif failure == 'criterion':
                record['screen']['verdict']['criteria']['resolved_ending'] = False
            elif failure == 'issues':
                record['screen']['verdict']['issues'] = ['The shown cut ends before an outcome.']
            elif failure == 'binding':
                record['screen']['binding'] = 'c' * 64
            elif failure == 'source':
                record['screen']['source_sha256'] = 'c' * 64
            elif failure == 'image':
                record['case']['frames'][0]['sha256'] = 'c' * 64
            else:
                record['screen']['verdict']['proofs'][0]['quote'] = 'An invented offscreen cause.'
            with self.subTest(failure=failure):
                self.assertEqual(self.status(analysis, record, plan), 'ready')
                original_native = copy.deepcopy(record['review'])
                _, scoped = candidates.prototype_plan(analysis, record['case'], record['proposal'])
                scoped['candidate_evidence'] = record
                self.assertEqual(candidates.inspect_candidate_quality(scoped, plan)['status'], 'unresolved')
                analysis['candidate_records'] = [record]
                result = candidates.compile_candidates(analysis, None)
                self.assertEqual(result['candidates'], [])
                self.assertTrue(result['declined'])
                self.assertTrue(all(not draft['export_eligible'] for draft in result['drafts']))
                self.assertEqual(record['review'], original_native)

    def test_duplicate_unapproved_source_drafts_are_deduplicated_before_requested_count(self):
        analysis, original, _ = candidate_fixture()
        original['review']['resolved'] = False
        duplicate = copy.deepcopy(original)
        duplicate['case']['id'] = 'another_hypothesis_for_same_source'
        distinct = copy.deepcopy(original)
        distinct['case']['id'] = 'a_different_source_range'
        last = distinct['case']['units'][-1]['id']
        distinct['proposal']['cuts'] = [{'first': last, 'last': last}]
        analysis['candidate_records'] = [original, duplicate, distinct]
        before = copy.deepcopy(analysis)
        result = candidates.compile_candidates(analysis, {'max_clips': 2})
        self.assertEqual(result['candidates'], [])
        self.assertEqual(len(result['drafts']), 2)
        identities = [draft['id'] for draft in result['drafts']]
        self.assertEqual(len(set(identities)), 2)
        self.assertTrue(all(not draft['export_eligible'] for draft in result['drafts']))
        self.assertEqual(analysis, before)
        analysis['candidate_records'] = [duplicate, original, distinct]
        self.assertEqual([draft['id'] for draft in candidates.compile_candidates(analysis, {'max_clips': 2})['drafts']],
                         identities)
        self.assertEqual([draft['id'] for draft in candidates.compile_candidates(analysis, {'max_clips': 1})['drafts']],
                         identities[:1])

    def test_story_proof_cannot_borrow_frame_from_another_unit(self):
        analysis, record, plan = candidate_fixture()
        record['review']['proofs'][0].update(mode='appearance', quote='', frames=[3])
        with self.assertRaises(ValueError):
            self.status(analysis, record, plan)
        _, scoped = candidates.prototype_plan(analysis, record['case'], record['proposal'])
        scoped['candidate_evidence'] = record
        self.assertEqual(candidates.inspect_candidate_quality(scoped, plan)['status'], 'unresolved')
        analysis['candidate_records'] = [record]
        self.assertEqual(candidates.compile_candidates(analysis, None)['candidates'], [])

    def test_native_dialogue_quote_preserves_complete_utterance_longer_than_500_characters(self):
        analysis = source_fixture()
        complete = ' '.join(f'Original source word {index}.' for index in range(60))
        self.assertGreater(len(complete), 500)
        words = complete.split()
        analysis['transcript']['words'] = [
            {'start': index * 20. / len(words), 'end': (index + 1) * 20. / len(words), 'text': word}
            for index, word in enumerate(words)] + analysis['transcript']['words'][1:]
        analysis['transcript']['segments'][0]['text'] = complete
        analysis, record, plan = candidate_fixture(analysis)
        schema = candidates.review_schema(record['case'], record['proposal'], plan)
        self.assertEqual(schema['properties']['dialogue']['items']['properties']['quote']['maxLength'], len(complete))
        self.assertEqual(schema['properties']['proofs']['items']['properties']['quote']['maxLength'], len(complete))
        self.assertEqual(record['review']['dialogue'][0]['quote'], complete)
        self.assertEqual(self.status(analysis, record, plan), 'ready')
        _, scoped = candidates.prototype_plan(analysis, record['case'], record['proposal'])
        scoped['candidate_evidence'] = copy.deepcopy(record)
        self.assertEqual(candidates.inspect_candidate_quality(scoped, plan)['status'], 'passed')
        for malformed in ('truncated_quote', 'invented_quote', 'overlong_evidence'):
            invalid = copy.deepcopy(record)
            row = invalid['review']['dialogue'][0]
            if malformed == 'truncated_quote':
                row['quote'] = complete[:500]
            elif malformed == 'invented_quote':
                row['quote'] = complete.replace('word 0.', 'fabricated phrase.', 1)
            else:
                row['evidence'] = 'x' * 501
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                self.status(analysis, invalid, plan)
        self.assertEqual(candidates.proposal_schema(record['case'])['properties']['title']['maxLength'], 500)

    def test_same_cut_establishing_shot_and_reaction_do_not_require_tiny_edge_unit_proofs(self):
        for multiple_cuts in (False, True):
            analysis, record, plan = establishing_reaction_fixture(multiple_cuts=multiple_cuts)
            kept = candidates.selected_units(record['case'], record['proposal'])
            opening, _, ending = record['review']['proofs']
            self.assertEqual(kept[0]['text'], '')
            self.assertEqual(kept[-1]['text'], '')
            self.assertNotEqual(opening['unit'], kept[0]['id'])
            self.assertNotEqual(ending['unit'], kept[-1]['id'])
            with self.subTest(multiple_cuts=multiple_cuts):
                self.assertEqual(self.status(analysis, record, plan), 'ready')
                analysis['candidate_records'] = [record]
                self.assertEqual(len(candidates.compile_candidates(analysis, None)['candidates']), 1)
                # Whole-story criteria and actual boundary proofs still apply.
                record['review']['criteria']['suitable_pacing'] = False
                self.assertEqual(self.status(analysis, record, plan), 'needs_review')

    def test_opening_and_ending_proofs_cannot_move_to_another_retained_cut(self):
        for phase in ('opening', 'ending'):
            analysis, record, plan = establishing_reaction_fixture(multiple_cuts=True)
            self.assertEqual(len(plan['parts'][0]['cuts']), 2)
            self.assertEqual(self.status(analysis, record, plan), 'ready')
            proofs = record['review']['proofs']
            if phase == 'opening':
                # Maintain chronological proof order; only first-cut ownership
                # is wrong, rather than merely reversing narrative phases.
                proofs[0] = {**copy.deepcopy(proofs[2]), 'phase': 'opening'}
                proofs[1] = {**copy.deepcopy(proofs[2]), 'phase': 'development'}
            else:
                proofs[2] = {**copy.deepcopy(proofs[1]), 'phase': 'ending'}
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, 'actual opening or ending'):
                self.status(analysis, record, plan)

    def test_dialogue_schema_excludes_silent_units_and_silent_partners(self):
        analysis, record, plan = establishing_reaction_fixture(multiple_cuts=True)
        case, proposal = record['case'], record['proposal']
        selected = candidates.selected_units(case, proposal)
        spoken = [unit['id'] for unit in selected if unit['text']]
        silent = next(unit for unit in selected if not unit['text'])
        schema = candidates.review_schema(case, proposal, plan)
        dialogue = schema['properties']['dialogue']['items']['properties']
        self.assertEqual(dialogue['unit']['enum'], spoken)
        self.assertEqual(dialogue['partners']['items']['enum'], spoken)
        self.assertNotIn(silent['id'], dialogue['unit']['enum'])
        for mode in ('silent_row', 'silent_partner'):
            invalid = copy.deepcopy(record)
            if mode == 'silent_row':
                invalid['review']['dialogue'].append({'unit': silent['id'], 'quote': '',
                    'status': 'self_contained', 'partners': [], 'evidence': 'This silent interval has no ASR.'})
            else:
                invalid['review']['dialogue'][0].update(status='question_answered', partners=[silent['id']])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.status(analysis, invalid, plan)

    def test_story_speech_proof_cannot_invent_or_borrow_other_utterance(self):
        analysis, record, plan = candidate_fixture()
        record['review']['proofs'][0]['quote'] = record['case']['units'][1]['text']
        with self.assertRaisesRegex(ValueError, 'ASR'):
            self.status(analysis, record, plan)

    def test_motion_requires_distinct_ordered_owned_observed_states(self):
        analysis, record, plan = candidate_fixture()
        opening = record['review']['proofs'][0]
        opening.update(mode='change', quote='', frames=[1, 2], motion=[
            {'frame': 1, 'state': 'The original door is closed.'},
            {'frame': 2, 'state': 'The original door is open.'}])
        self.assertEqual(self.status(analysis, record, plan), 'ready')
        for motion in (
            [{'frame': 1, 'state': 'Closed'}],
            [{'frame': 2, 'state': 'Closed'}, {'frame': 1, 'state': 'Open'}],
            [{'frame': 1, 'state': 'Closed'}, {'frame': 2, 'state': 'Closed'}],
            [{'frame': 1, 'state': 'Closed'}, {'frame': 3, 'state': 'Open'}],
        ):
            opening['motion'] = motion
            with self.subTest(motion=motion), self.assertRaises(ValueError):
                self.status(analysis, record, plan)

    def test_identical_original_images_cannot_prove_change_with_different_state_text(self):
        analysis, record, plan = candidate_fixture()
        first, second = record['case']['frames'][:2]
        self.assertLess(first['time'], second['time'])
        second['sha256'] = first['sha256']
        record['review']['proofs'][0].update(mode='change', quote='', frames=[1, 2], motion=[
            {'frame': 1, 'state': 'The original door is closed.'},
            {'frame': 2, 'state': 'The original door is open.'}])
        with self.assertRaisesRegex(ValueError, 'Identical original images'):
            self.status(analysis, record, plan)
        analysis['candidate_records'] = [record]
        self.assertEqual(candidates.compile_candidates(analysis, None)['candidates'], [])

    def test_source_only_discovery_never_passes_final_quality_or_acquires_export_authority(self):
        from app.final_quality import inspect_final_quality
        for misleading_evidence in (False, True):
            analysis, record, plan = candidate_fixture()
            analysis.update(analysis_contract='standalone_source_v2', quality_policy='standalone_source_v2', events=[])
            if misleading_evidence:
                # Even copied downstream fields cannot grant authority to a
                # source-only discovery record through the legacy quality gate.
                analysis.update(quality_policy=candidates.CONTRACT, candidate_evidence=record)
            before = copy.deepcopy((analysis, plan))
            with self.subTest(misleading_evidence=misleading_evidence):
                result = inspect_final_quality(analysis, plan)
                self.assertEqual(result['status'], 'unresolved')
                self.assertEqual(result['problems'], [
                    {'code': 'discovery_hypothesis_only', 'recovery_stage': 'candidate_review'}])
                self.assertEqual(result['evidence_chain'], [])
                self.assertNotIn('export_eligible', plan)
                self.assertEqual((analysis, plan), before)

    def test_dialogue_requires_full_utterance_and_actual_retained_partner(self):
        for mode in ('missing_utterance', 'partial_quote', 'self_partner', 'missing_partner', 'duplicate_utterance'):
            analysis, record, plan = candidate_fixture()
            rows = record['review']['dialogue']
            if mode == 'missing_utterance':
                rows.pop()
            elif mode == 'partial_quote':
                rows[0]['quote'] = 'Can you open'
            elif mode == 'self_partner':
                rows[0]['partners'] = [rows[0]['unit']]
            elif mode == 'missing_partner':
                rows[0]['partners'] = []
            else:
                rows[-1] = copy.deepcopy(rows[0])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.status(analysis, record, plan)

    def test_every_actual_boundary_requires_safe_original_edge_proof(self):
        for mode in ('missing_edge', 'duplicate_edge', 'wrong_anchor', 'unsafe_edge'):
            analysis, record, plan = candidate_fixture()
            edges = record['review']['boundaries']
            if mode == 'missing_edge':
                edges.pop()
            elif mode == 'duplicate_edge':
                edges[-1] = copy.deepcopy(edges[0])
            elif mode == 'wrong_anchor':
                edges[0]['frames'] = [2]
            else:
                edges[0]['safe'] = False
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.status(analysis, record, plan)

    def test_source_ranges_cannot_be_broadened_or_shrunk_after_review(self):
        for ranges in ([{'start': 0., 'end': 61.}], [{'start': 0., 'end': 20.}], []):
            analysis, record, _ = candidate_fixture()
            record['case']['source_ranges'] = ranges
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                candidates.validate_case(analysis, record['case'])

    def test_source_or_frame_ownership_mutation_invalidates_review(self):
        for mode in ('transcript', 'unit', 'frame_time', 'duplicate_frame', 'frame_hash'):
            analysis, record, plan = candidate_fixture()
            case = record['case']
            if mode == 'transcript':
                analysis['transcript']['segments'][0]['text'] = 'A changed original source.'
            elif mode == 'unit':
                case['units'][0]['end'] -= 1
            elif mode == 'frame_time':
                case['frames'][0]['time'] = 21.
            elif mode == 'duplicate_frame':
                case['frames'][1]['index'] = case['frames'][0]['index']
            else:
                case['frames'][0]['sha256'] = 'z' * 64
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.status(analysis, record, plan)

    def test_reviewed_timeline_cannot_be_replaced_after_native_approval(self):
        analysis, record, plan = candidate_fixture()
        _, scoped = candidates.prototype_plan(analysis, record['case'], record['proposal'])
        scoped['candidate_evidence'] = record
        forged = copy.deepcopy(plan)
        forged['parts'][0]['cuts'][0]['end'] -= 1
        self.assertEqual(candidates.inspect_candidate_quality(scoped, forged)['status'], 'unresolved')

    def test_malformed_candidate_does_not_veto_independent_approved_candidate(self):
        analysis, record, _ = candidate_fixture()
        malformed = copy.deepcopy(record)
        malformed['case']['id'] = 'bad_hypothesis'
        malformed['proposal']['cuts'][0]['first'] = 'not_an_original_unit'
        analysis['candidate_records'] = [malformed, record]
        result = candidates.compile_candidates(analysis, None)
        self.assertEqual([row['arc_id'] for row in result['candidates']], ['h1'])
        self.assertTrue(any(row['arc_id'] == 'bad_hypothesis' for row in result['declined']))


class ProposalBeatBindingTests(unittest.TestCase):
    def fixture(self):
        analysis, record, _ = candidate_fixture()
        analysis['proposal_policy'] = copy.deepcopy(candidates.PROPOSAL_POLICY)
        case, proposal = record['case'], record['proposal']
        case['proposal_policy'] = copy.deepcopy(candidates.PROPOSAL_POLICY)
        case['proposal_observations'] = copy.deepcopy(case['frames'])
        units = case['units']
        proposal['beats'] = [
            {'role': role, 'kind': 'speech', 'first': unit['id'], 'last': unit['id'],
             'quote': unit['text'], 'frames': [], 'states': []}
            for role, unit in zip(('setup', 'development', 'payoff'), units)]
        return analysis, record

    def test_exact_own_substring_and_multiple_groups(self):
        analysis, record = self.fixture()
        case, proposal = record['case'], record['proposal']
        first, _, last = case['units']
        proposal['beats'][0]['quote'] = 'open the door'
        proposal['beats'][1] = copy.deepcopy(proposal['beats'][0])
        proposal['beats'][1]['role'] = 'development'
        proposal['cuts'] = [{'first': unit['id'], 'last': unit['id']} for unit in (first, last)]
        plan, _ = candidates.prototype_plan(analysis, case, proposal)
        self.assertEqual(len(plan['parts'][0]['cuts']), 2)
        candidates.validate_proposal_binding(case, proposal, plan, plan['proposal_binding'])
        proposal['beats'][0]['quote'] = last['text']
        with self.assertRaises(ValueError):
            candidates.proposal_ranges(case, proposal)

    def test_change_whole_span_and_actual_geometry(self):
        analysis, record = self.fixture()
        case, proposal = record['case'], record['proposal']
        proposal['beats'][-1] = {'role': 'payoff', 'kind': 'change',
            'first': case['units'][1]['id'], 'last': case['units'][2]['id'],
            'quote': '', 'frames': [3, 6], 'states': ['standing', 'fallen']}
        plan, _ = candidates.prototype_plan(analysis, case, proposal)
        broken = copy.deepcopy(plan)
        broken['parts'][0]['cuts'][0]['end'] = 45.
        with self.assertRaises(ValueError):
            candidates.proposal_binding(case, proposal, broken)
        stale = copy.deepcopy(plan['proposal_binding'])
        stale['timeline_digest'] = 'changed'
        with self.assertRaises(ValueError):
            candidates.validate_proposal_binding(case, proposal, plan, stale)
        proposal['cuts'] = [{'first': case['units'][0]['id'], 'last': case['units'][1]['id']}]
        with self.assertRaises(ValueError):
            candidates.proposal_ranges(case, proposal)

    def test_observation_failures(self):
        for defect in ('reverse', 'same_pixels', 'owner', 'source', 'unknown'):
            with self.subTest(defect=defect):
                analysis, record = self.fixture()
                case, proposal = record['case'], record['proposal']
                proposal['beats'][-1].update(kind='change', quote='', frames=[5, 6], states=['before', 'after'])
                if defect == 'reverse':
                    proposal['beats'][-1]['frames'] = [6, 5]
                elif defect == 'same_pixels':
                    case['proposal_observations'][5]['sha256'] = case['proposal_observations'][4]['sha256']
                elif defect == 'owner':
                    case['proposal_observations'][4]['unit'] = case['units'][0]['id']
                elif defect == 'source':
                    case['proposal_observations'][4]['source_sha256'] = 'b'*64
                else:
                    proposal['beats'][-1]['frames'] = [5, 999]
                with self.assertRaises(ValueError):
                    candidates.proposal_ranges(case, proposal)

    def test_omitted_middle_and_disconnected_catalog_fail(self):
        for defect in ('omitted_middle', 'disconnected'):
            with self.subTest(defect=defect):
                analysis, record = self.fixture()
                case, proposal = record['case'], record['proposal']
                proposal['beats'][1] = copy.deepcopy(proposal['beats'][0])
                proposal['beats'][1]['role'] = 'development'
                proposal['beats'][-1].update(kind='change', first=case['units'][0]['id'],
                    quote='', frames=[1, 6], states=['before', 'after'])
                if defect == 'omitted_middle':
                    proposal['cuts'] = [{'first': unit['id'], 'last': unit['id']}
                        for unit in (case['units'][0], case['units'][2])]
                else:
                    case['units'][1]['start'] += .5
                with self.assertRaises(ValueError):
                    candidates.proposal_ranges(case, proposal)

    def test_appearance_and_safe_draft_policy_copy(self):
        analysis, record = self.fixture()
        case, proposal = record['case'], record['proposal']
        proposal['beats'][-1].update(kind='appearance', quote='', frames=[5], states=['door open'])
        plan, _ = candidates.prototype_plan(analysis, case, proposal)
        self.assertIn('proposal_binding', plan)
        draft, scoped = candidates.prototype_plan(analysis, case, proposal, draft=True)
        self.assertNotIn('proposal_binding', draft)
        self.assertNotIn('proposal_policy', scoped)
        self.assertIn('proposal_policy', analysis)
        self.assertIn('proposal_observations', case)
        mismatched = copy.deepcopy(analysis)
        mismatched.pop('proposal_policy')
        with self.assertRaises(ValueError):
            candidates.prototype_plan(mismatched, case, proposal)

    def test_quality_rejects_missing_binding(self):
        analysis, record = self.fixture()
        plan, scoped = candidates.prototype_plan(analysis, record['case'], record['proposal'])
        record['timeline_digest'] = candidates.timeline_digest(plan)
        scoped['candidate_evidence'] = record
        result = candidates.inspect_candidate_quality(scoped, plan)
        self.assertEqual(result['status'], 'unresolved')
        self.assertIn('binding', result['problems'][0]['detail'])

    def test_policy_role_and_nonviable_hardening(self):
        for defect in ('bool_policy', 'case_bool', 'roles', 'nonviable_beats', 'nonviable_cuts'):
            with self.subTest(defect=defect):
                analysis, record = self.fixture()
                case, proposal = record['case'], record['proposal']
                if defect == 'bool_policy':
                    analysis['proposal_policy'] = {'version': True}
                elif defect == 'case_bool':
                    case['proposal_policy'] = {'version': True}
                elif defect == 'roles':
                    proposal['beats'][0]['role'], proposal['beats'][-1]['role'] = 'payoff', 'setup'
                else:
                    proposal['viable'] = False
                    if defect == 'nonviable_cuts':
                        proposal['beats'] = []
                with self.assertRaises(ValueError):
                    candidates.prototype_plan(analysis, case, proposal)
        analysis, record = self.fixture()
        record['proposal'].update(viable=False, beats=[], cuts=[])
        self.assertEqual(candidates.proposal_ranges(record['case'], record['proposal']), [])

    def test_all_preview_entries_are_owned_and_separate(self):
        for defect in ('bool_index', 'negative_index', 'owner', 'sha', 'time', 'alias'):
            with self.subTest(defect=defect):
                analysis, record = self.fixture()
                case, proposal = record['case'], record['proposal']
                frame = case['proposal_observations'][-1]  # All beats are speech: this is uncited.
                if defect == 'bool_index':
                    frame['index'] = True
                elif defect == 'negative_index':
                    frame['index'] = -1
                elif defect == 'owner':
                    frame['unit'] = 'foreign'
                elif defect == 'sha':
                    frame['sha256'] = 'x'*64
                elif defect == 'time':
                    frame['time'] = float('nan')
                else:
                    case['proposal_observations'] = case['frames']
                with self.assertRaises(ValueError):
                    candidates.proposal_ranges(case, proposal)
                with self.assertRaises(ValueError):
                    candidates.validate_case(analysis, case)

    def test_change_states_must_differ(self):
        analysis, record = self.fixture()
        record['proposal']['beats'][-1].update(kind='change', quote='', frames=[5, 6],
            states=[' Fallen ', 'fallen'])
        with self.assertRaises(ValueError):
            candidates.proposal_ranges(record['case'], record['proposal'])


if __name__ == '__main__':
    unittest.main()
