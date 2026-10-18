"""Source-only discovery; hypotheses never authorize a published candidate."""
from __future__ import annotations

import copy

from .content_identity import digest, file_sha256
from .execution_context import scope
from .json_store import atomic_json
from .model_perf import purpose


def analyze_standalone(source, probe, transcript, shots, scenes, source_evidence, job_dir,
                       sessions, provider, journal, diagnostics, report, cancelled):
    from .analysis_provider import _model_files_for_provider, provider_identity
    from .analysis_questions import QuestionLedger
    from .config import ROOT, STORY_MODEL, STORY_PROJECTOR
    from .episode_survey import survey_episode, build_episode_map
    source_sha = source_evidence['source_sha256']
    # Source discovery depends on its physical inputs and actual adapters only.
    # Candidate qualification, ranking and framing have separate downstream
    # signatures, and cannot invalidate this completed source record.
    model_files = []
    for path in _model_files_for_provider(provider, 'cinema'):
        stat = path.stat()
        model_files.append({'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns})
    identity = {'version': 2, 'source': source_sha, 'evidence': digest(source_evidence),
        'physical': digest({'probe': probe, 'transcript': transcript, 'shots': shots}),
        'scenes': scenes, 'provider': provider_identity(provider), 'model_files': model_files,
        'code': {name: file_sha256(ROOT/'app'/(name+'.py')) for name in
                 ('standalone_analysis', 'episode_survey', 'analysis_questions', 'discovery_regions',
                  'bounded_storyboard', 'source_identity', 'content_identity', 'json_store',
                  'analysis_continuation', 'checkpoint_lineage', 'analysis_provider',
                  'vision', 'deepseek', 'request_payload', 'antigravity_exchange', 'media_probe')}}
    questions = QuestionLedger(job_dir, source_sha, cancelled)

    def execute():
        report('analyze', .22, 'Обзор всей серии: речь и редкие кадры, включая тихие сцены')
        with purpose('episode_survey'), scope(stage='episode_survey'), sessions.session(job_dir, cancelled, 'local') as vision:
            survey = survey_episode(source, scenes, transcript, job_dir, vision, cancelled,
                source_evidence=source_evidence, journal=journal,
                ask=lambda question, callback: questions.run(question, callback, 'local'))
        report('analyze', .35, 'Ищем самостоятельные истории и необходимый им контекст')
        with purpose('episode_map'), scope(stage='episode_map'), sessions.session(job_dir, cancelled, provider,
                model=STORY_MODEL, projector=STORY_PROJECTOR, thinking=True) as vision:
            episode_map = build_episode_map(survey, transcript, job_dir, vision, cancelled, journal=journal,
                ask=lambda question, callback: questions.run(question, callback, provider))
        return {'analysis_contract': 'standalone_source_v2', 'quality_policy': 'standalone_source_v2',
            'source_sha256': source_sha, 'source_evidence_digest': identity['evidence'],
            'probe': copy.deepcopy(probe), 'transcript': copy.deepcopy(transcript),
            'shots': copy.deepcopy(shots), 'scenes': copy.deepcopy(scenes), 'events': [],
            'episode_map': episode_map,
            'check_policy': {'version': 2, 'objective': 'standalone_shorts',
                'discovery': 'whole_source_sparse', 'authority': 'hypothesis_only',
                'qualification': 'whole_candidate_downstream', 'publication_eligible': False,
                'framing': 'final_candidates_only'}}

    result = journal.run('standalone_source', identity, execute, provider)
    # Keep legacy selective and full-perception snapshots intact. This record
    # carries source facts and hypotheses, with no candidate approval authority.
    atomic_json(job_dir/'standalone-source.json', result)
    atomic_json(job_dir/'standalone-source.meta.json', {'version': 2, 'identity': digest(identity),
        'source_sha256': source_sha, 'analysis_contract': result['analysis_contract']})
    return result
