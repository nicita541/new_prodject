"""Read-only eligible-event queues for native cloud-review progress.

These indices describe events examined by a known specialist. They are never
used to filter workers, rewrite model requests, or predict paid request counts.
"""
from __future__ import annotations

from functools import partial
import json
from pathlib import Path


def _source_available(job_dir):
    from .config import ROOT
    try:
        source = Path(json.loads((job_dir/'source.json').read_text('utf-8'))['path']).resolve()
        return source.is_relative_to(ROOT.resolve()) and source.is_file()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def review_indices(events, transcript, shots, job_dir, refiner):
    """Return original eligible indices; unknown native scope returns ``None``.

    Cache hits remain eligible local work. Exact cache validation and dynamic
    follow-up questions belong to the unchanged native worker, not this counter.
    """
    options = {}
    while isinstance(refiner, partial):
        if refiner.args:
            return None
        options = {**(refiner.keywords or {}), **options}
        refiner = refiner.func
    from .titles import refine_titles, title_units, _candidates
    from .closing import refine_closing_novelty, _ending_anchor
    from .source_roles import refine_source_roles, confirmed_exclusions
    from .review_scope import target_units
    from .story_review import candidate_units
    from .source_ranges import subtract_ranges

    directory = Path(job_dir)
    if refiner is refine_titles:
        if not _source_available(directory):
            return ()
        return tuple(index for index, event in enumerate(events)
                     if not event.get('credit_montage') and target_units(event,
                         _candidates(event, title_units(event['start'],event['end'],transcript,shots),transcript),
                         'titles'))
    if refiner is refine_closing_novelty:
        duration = options.get('episode_duration')
        if duration is None:
            duration = max((event['end'] for event in events), default=0)
        event_ids = options.get('event_ids')
        indices = []
        for index, event in enumerate(events):
            if event_ids is not None and event['id'] not in event_ids:
                continue
            if not (_ending_anchor(event, duration) or event.get('closing_candidate')
                    or event.get('closing_novelty_anchor') or 'closing' in event.get('review_targets', [])):
                continue
            units = (event.get('units') if event.get('analysis_chunks') else None) or candidate_units(
                event['start'],event['end'],transcript,shots)
            if not target_units(event,units,'closing'):
                continue
            visual = (directory/'visual').resolve()
            image = (visual/(str(event['id'])+'.jpg')).resolve()
            if image.is_relative_to(visual) and image.is_file():
                indices.append(index)
        return tuple(indices)
    if refiner is refine_source_roles:
        if not _source_available(directory):
            return ()
        event_ids = options.get('event_ids')
        indices = []
        for index, event in enumerate(events):
            if event_ids is not None and event['id'] not in event_ids:
                continue
            previous_failure = event.get('source_role_unresolved')
            retry = bool(options.get('retry_unresolved') and previous_failure)
            if not (retry or event.get('contains_credits') or event.get('credit_montage')
                    or 'source_roles' in event.get('review_targets', [])
                    or any(event.get(key) for key in ('preview_candidate','promotion_candidate','source_role_candidate'))):
                continue
            review_ranges = (previous_failure.get('source_ranges') or [event]) if retry else event.get('selected_ranges',[event])
            selections = subtract_ranges(review_ranges,confirmed_exclusions(event))
            units = candidate_units(event['start'],event['end'],transcript,shots)
            units = [unit for unit in units if any(unit['start'] < span['end'] and unit['end'] > span['start']
                                                  for span in selections)]
            if target_units(event,units,'source_roles'):
                indices.append(index)
        return tuple(indices)
    return None
