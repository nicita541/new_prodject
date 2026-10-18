"""Frame only final standalone cuts, retaining native proof and current styling."""
from __future__ import annotations

import copy
import math
import re
from pathlib import Path

from .analysis_provider import framing_provider, provider_identity
from .cancellation import check_cancelled
from .config import STORY_MODEL, STORY_PROJECTOR
from .content_identity import digest, file_sha256
from .framing import MIN_CONFIDENCE, refine_focus
from .model_perf import purpose as inference_purpose
from .source_identity import source_identity
from .source_ranges import intersect_ranges
from .standalone_planner import _plan
from .vision import AnalysisVisionSessions, vision_session

VERSION = 1
POLICY = 'final-native-cuts-only-focus-overlay-conservative-cinema-v1'


def _model_stat(path):
    path = Path(path)
    result = {'path': str(path.resolve())}
    if path.is_file():
        stat = path.stat()
        result.update(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
    return result


def _code_identity(cancelled):
    root = Path(__file__).parent
    return {name: file_sha256(root / (name + '.py'), cancelled) for name in
            ('candidate_framing', 'framing', 'vision', 'analysis_provider', 'deepseek', 'request_payload')}


def _events_for_cuts(scoped, cuts):
    events = []
    for original in scoped['events']:
        event = copy.deepcopy(original)
        # Framing observes the actual output, including native speech handles.
        # Canonical selected_ranges remain untouched in scoped_analysis.
        selected = intersect_ranges([event], cuts)
        if selected:
            event['selected_ranges'] = selected
            event.pop('focus', None)
            event.pop('focus_warnings', None)
            events.append(event)
    return events


def _overlay(events):
    return {'events': [{'id': e['id'], 'focus': copy.deepcopy(e.get('focus', [])),
                        'focus_warnings': copy.deepcopy(e.get('focus_warnings', []))} for e in events]}


def _valid_overlay(saved, frame_events):
    if not isinstance(saved, dict) or set(saved) != {'events'} or not isinstance(saved['events'], list):
        return False
    if (not all(isinstance(e, dict) for e in saved['events'])
            or [e.get('id') for e in saved['events']] != [e['id'] for e in frame_events]):
        return False
    for event in saved['events']:
        if set(event) != {'id', 'focus', 'focus_warnings'}:
            return False
        if (not isinstance(event['focus'], list) or not isinstance(event['focus_warnings'], list)
                or not all(isinstance(w, str) for w in event['focus_warnings'])):
            return False
        for anchor in event['focus']:
            if not isinstance(anchor, dict):
                return False
            for name in ('time', 'x', 'y', 'confidence'):
                value = anchor.get(name)
                if type(value) not in (float, int) or not math.isfinite(value):
                    return False
                if name != 'time' and not 0 <= value <= 1:
                    return False
    return True


def _apply(candidate, overlay):
    scoped, native = candidate['scoped_analysis'], candidate['plan']
    updates = {event['id']: event for event in overlay['events']}
    for event in scoped['events']:
        if event['id'] in updates:
            event.update(copy.deepcopy(updates[event['id']]))
    rebuilt = _plan(scoped, native['semantic_ranges'])
    geometry = lambda plan: [(part['duration'], [(c['start'], c['end'], c.get('event_ids'))
                                               for c in part['cuts']]) for part in plan['parts']]
    if geometry(rebuilt) != geometry(native):
        raise ValueError('Candidate framing changed native cut geometry')
    for part, fresh in zip(native['parts'], rebuilt['parts']):
        for cut, focused in zip(part['cuts'], fresh['cuts']):
            cut['focus'] = copy.deepcopy(focused['focus'])
        warnings = [warning for event in scoped['events']
                    if event['id'] in {owner for cut in part['cuts'] for owner in cut.get('event_ids', [])}
                    for warning in event.get('focus_warnings', [])]
        uncertain = warnings or any(not cut['focus'] or
            any(anchor.get('confidence', 0) < MIN_CONFIDENCE for anchor in cut['focus']) for cut in part['cuts'])
        if uncertain:
            warning = 'Кадрирование не подтверждено: сохранён исходный кадр целиком (cinema).'
            part['layout'] = 'cinema'
            part['framing_fallback'] = {'reason': 'uncertain_focus', 'warnings': copy.deepcopy(warnings)}
            if warning not in native.setdefault('warnings', []):
                native['warnings'].append(warning)
        else:
            part.pop('framing_fallback', None)
    # Keep the native plan's semantic event evidence coherent without replacing
    # any caption, rank, appearance, or unrelated candidate attribute.
    for event in native.get('events', []):
        if event['id'] in updates:
            event.update(copy.deepcopy(updates[event['id']]))


def frame_final_candidates(source, compiled, job_dir, provider, report, cancelled, *,
                           journal, layout, allow_new_session=True):
    """Return a deep copy; cache only focus overlays, never styled plans.

    One session owner spans cold candidates and loads its local runtime lazily.
    Warm overlays are checked before entering any model session.
    """
    result = copy.deepcopy(compiled)
    check_cancelled(cancelled)
    if layout != 'portrait' or not result.get('candidates'):
        return result
    job_dir = Path(job_dir).resolve()
    if not job_dir.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('Candidate framing directory escapes workspace')
    focus_provider = framing_provider(provider)
    common = {'version': VERSION, 'policy': POLICY, 'source': source_identity(Path(source), cancelled)['sha256'],
              'provider': provider_identity(focus_provider),
              'models': [_model_stat(STORY_MODEL), _model_stat(STORY_PROJECTOR)],
              'code': _code_identity(cancelled)}
    with AnalysisVisionSessions(job_dir, cancelled, factory=vision_session) as sessions:
        for candidate in result['candidates']:
            check_cancelled(cancelled)
            scoped, native = candidate['scoped_analysis'], candidate['plan']
            cuts = [cut for part in native['parts'] for cut in part['cuts']]
            frame_events = _events_for_cuts(scoped, cuts)
            inputs = {**common, 'probe': scoped['probe'], 'transcript': scoped['transcript'],
                      'shots': scoped.get('shots', []), 'events': frame_events,
                      'canonical_events': [{k: v for k, v in e.items() if k not in ('focus', 'focus_warnings')}
                                           for e in scoped['events']],
                      'cuts': [{'start': c['start'], 'end': c['end'], 'event_ids': c.get('event_ids', [])} for c in cuts]}
            # Compiler IDs are safe directory components, never model paths.
            ident = candidate['id']
            if not isinstance(ident, str) or not re.fullmatch(r'short_[A-Za-z0-9_-]{1,128}', ident):
                raise ValueError('Invalid standalone candidate identity')
            name = 'candidate_framing_' + digest(ident)[:24]
            saved = journal.load(name, inputs)
            if not _valid_overlay(saved, frame_events):
                if not allow_new_session:
                    saved = _overlay(frame_events)
                else:
                    directory = job_dir / 'candidate-framing' / ident
                    directory.mkdir(parents=True, exist_ok=True)
                    with inference_purpose('framing'), sessions.session(job_dir, cancelled, focus_provider,
                            model=STORY_MODEL, projector=STORY_PROJECTOR) as vision:
                        focused = refine_focus(Path(source), scoped['probe'], scoped['transcript'],
                            scoped.get('shots', []), frame_events, directory, vision, report, cancelled)
                    check_cancelled(cancelled)
                    saved = _overlay(focused)
                    if not _valid_overlay(saved, frame_events):
                        raise ValueError('Candidate framing returned invalid focus evidence')
                    journal.save(name, inputs, saved, focus_provider)
            _apply(candidate, saved)
    return result
