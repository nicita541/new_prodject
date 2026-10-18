"""Reuse exact renders only from immutable, explicitly owned ancestor revisions."""
from __future__ import annotations

from .artifact_publication import current_revision, resolve_revision_output, PublicationError
from .cancellation import check_cancelled
from .checkpoint_lineage import ancestors
from .media import EXPORT_VALIDATION_VERSION


def inherited_render(job_dir, fingerprint, cancelled=lambda: False):
    """Return publication reference + presentation metadata, or a safe cache miss.

    Candidate approval precedes this lookup. A fingerprint binds the actual cuts,
    captions, source and render inputs; similarity or shared source is insufficient.
    Corrupt media is disposable, while invalid ownership/lineage fails closed.
    """
    check_cancelled(cancelled)
    for origin in ancestors(job_dir):
        check_cancelled(cancelled)
        try:
            record = current_revision(origin, metadata_only=True, cancelled=cancelled)
            if record is None:
                continue
            for part in record['plan'].get('parts', []):
                if part.get('render_fingerprint') != fingerprint:
                    continue
                filename = f"part_{part['index']:03}.mp4"
                artifact = next((item for item in record['artifacts']
                                 if item['video']['filename'] == filename), None)
                if artifact is None or artifact['full_decode_version'] != EXPORT_VALIDATION_VERSION:
                    continue
                # Resolves and hashes this pair only, including transitive refs.
                resolve_revision_output(origin, record['revision_id'], filename, cancelled=cancelled)
                return {'reference': {'job_id': origin.name, 'revision_id': record['revision_id'],
                            'video_filename': filename,
                            'subtitles_filename': artifact['subtitles']['filename']},
                        'full_decode_version': artifact['full_decode_version'],
                        'music_track': part.get('music_track'), 'encoder': None}
        except InterruptedError:
            raise
        except (PublicationError, OSError, ValueError, KeyError, TypeError):
            # Never repair or upgrade an ancestor. Render current inputs locally.
            continue
    return None
