"""Technically validated continuous-source drafts, never approved Shorts."""
from __future__ import annotations

import copy
from pathlib import Path
import re

from .artifact_publication import current_revision, publish_revision, resolve_output
from .cancellation import check_cancelled
from .content_identity import digest, file_sha256
from .media import EXPORT_VALIDATION_VERSION

_ID = re.compile(r'draft_[0-9a-f]{20}\Z')


def draft_store(job_dir, identifier):
    if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
        raise ValueError('Invalid draft ID')
    root = Path(job_dir).resolve()
    store = root/'drafts'/identifier
    store.resolve().relative_to(root)
    return store


def _summary(draft, job_id, status):
    result = {k: copy.deepcopy(v) for k, v in draft.items() if k != 'plan'}
    result.update(status=status, export_eligible=False)
    if status == 'rendered_needs_review':
        base = f"/api/jobs/{job_id}/drafts/{draft['id']}/files/part_001"
        result.update(video_url=base+'.mp4', subtitle_url=base+'.srt',
                      duration=draft['plan']['parts'][0]['duration'], layout='cinema')
    return result


def render_drafts(drafts, analysis, source, source_sha, job_dir, report, cancelled, timings, backend):
    from .config import ROOT
    from .planner import validate_plan
    from .subtitles import style_identity
    from .edit_integrity import inspect_edits
    result, failures, encoder = [], [], None
    for draft in drafts:
        check_cancelled(cancelled)
        plan = copy.deepcopy(draft['plan'])
        try:
            if (plan.get('draft') is not True or plan.get('export_eligible') is not False
                    or len(plan.get('parts', [])) != 1 or len(plan['parts'][0].get('cuts', [])) != 1
                    or not 0 < plan['parts'][0]['duration'] <= 120):
                raise ValueError('Safe draft requires one continuous original-source range')
            scoped = {k: analysis[k] for k in ('probe', 'transcript', 'shots', 'speech_handle_overrides', 'review_scope') if k in analysis}
            scoped['events'] = plan['events']
            validate_plan(plan, scoped, allow_draft=True)
            if inspect_edits(scoped, plan):
                raise ValueError('Unsafe draft edit geometry')
            part = plan['parts'][0]
            # Unqualified framing must not crop faces or manufacture composition.
            part.update(layout='cinema', caption_style='classic')
            plan['editing'] = {'layout': 'cinema', 'caption_style': 'classic'}
            fingerprint = digest({'source': source_sha, 'probe': analysis['probe'],
                'part': {k: part.get(k) for k in ('cuts', 'duration', 'subtitles', 'layout', 'caption_style')},
                'style': style_identity('classic'), 'media': file_sha256(ROOT/'app/media.py'),
                'draft_renderer': file_sha256(Path(__file__)), 'full_decode_version': EXPORT_VALIDATION_VERSION})
            store = draft_store(job_dir, draft['id'])
            previous = current_revision(store, cancelled=cancelled)
            if previous is None or previous['plan'].get('draft_render_fingerprint') != fingerprint:
                output, work = store/'rendered', store/'work'
                output.mkdir(parents=True, exist_ok=True)
                if encoder is None:
                    encoder = backend.choose_encoder(Path(job_dir)/'render', cancelled)
                path = backend.render_part(source, part, analysis['probe'], output, work,
                    encoder, cancelled, background_music=None, finishing=None)
                plan['draft_render_fingerprint'] = fingerprint
                publish_revision(store, plan, [{'video': path, 'subtitles': path.with_suffix('.srt'),
                    'candidate_id': draft['id'], 'full_decode_version': EXPORT_VALIDATION_VERSION}],
                    producer_id=Path(job_dir).name, attempt_id=timings['run_id'], cancelled=cancelled)
            result.append(_summary({**draft, 'plan': plan}, Path(job_dir).name, 'rendered_needs_review'))
        except InterruptedError:
            raise
        except (OSError, RuntimeError, ValueError, TimeoutError) as error:
            result.append(_summary(draft, Path(job_dir).name, 'technical_failed'))
            failures.append({'stage': 'draft_rendering', 'candidate_id': draft['id'],
                'reason': 'draft_render_failed', 'error_type': type(error).__name__, 'export_eligible': False,
                'message': 'Не удалось подготовить видео черновика'})
        report('rendering', .98, f'Подготовлено черновиков для проверки: {len(result)} из {len(drafts)}')
    return result, failures


def draft_output(job_dir, identifier, filename):
    store = draft_store(job_dir, identifier)
    record = current_revision(store, verify_artifacts=False)
    if (record is None or record['plan'].get('draft') is not True
            or record['plan'].get('export_eligible') is not False):
        raise ValueError('Draft is not published for review')
    return resolve_output(store, filename, allow_legacy=False)
