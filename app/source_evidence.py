"""Immutable physical observations shared by all candidate edit plans."""
from __future__ import annotations

import copy

VERSION = 1


def capture(journal, probe, transcript, shots, raw_candidates, perception, preparation):
    """Copy physical observations, never references to mutable event/plan files."""
    inputs = {'preparation': preparation, 'probe': probe,
              'raw_candidates': raw_candidates, 'perception': perception}
    saved = journal.load('source_evidence', inputs)
    if saved is not None:
        return saved
    evidence = {'version': VERSION, 'source_sha256': journal.context['source'],
                'probe': copy.deepcopy(probe), 'transcript': copy.deepcopy(transcript),
                'shots': copy.deepcopy(shots), 'raw_candidates': copy.deepcopy(raw_candidates),
                'perception': copy.deepcopy(perception), 'preparation': copy.deepcopy(preparation),
                'provenance': {'speech': transcript.get('provenance', {'mode': preparation['transcript'].get('mode', 'automatic')}),
                               'visual_descriptors': 'measured_source_not_semantic_labels'}}
    journal.save('source_evidence', inputs, evidence, 'source_tools')
    return evidence
