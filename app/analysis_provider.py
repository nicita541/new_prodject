"""Analysis routing/settings and mandatory model files. No pipeline execution."""
from __future__ import annotations

from pathlib import Path

from app.config import VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR
from app.json_store import load_json

def analysis_provider(job_dir: Path) -> str:
    settings = job_dir / 'analysis-settings.json'
    provider = load_json(settings).get('provider', 'local') if settings.is_file() else 'local'
    if provider not in ('local', 'deepseek', 'hybrid', 'deepseek_plan', 'local_flash_story', 'local_fast_story', 'local_flash_story_budgeted', 'antigravity_manual'):
        raise ValueError('Неизвестный способ анализа')
    return provider


def provider_identity(provider):
    if provider == 'antigravity_manual':
        from .antigravity_exchange import PROFILE
        return dict(PROFILE)
    from .deepseek import provider_identity as native_identity
    return native_identity(provider)


def framing_provider(provider: str) -> str:
    return 'local' if provider in ('deepseek_plan', 'local_fast_story') else provider


def perception_provider(provider: str) -> str:
    """These story transports share unchanged local 4B source perception."""
    return 'local' if provider in ('deepseek_plan', 'antigravity_manual') else provider


def _model_files_for_provider(provider: str, layout: str = 'portrait') -> tuple[Path, ...]:
    """Only local models actually used by this provider are mandatory.

    DeepSeek Plan uses local 9B only for portrait framing; cinema keeps
    the source frame and needs just local 4B perception. Local story and
    hybrid routes still need 9B regardless of output layout.
    """
    if provider == 'deepseek_plan' and layout == 'cinema':
        return (VLM_MODEL, VLM_PROJECTOR)
    if provider in ('local_flash_story', 'local_flash_story_budgeted', 'deepseek', 'antigravity_manual'):
        return (VLM_MODEL, VLM_PROJECTOR)
    return (VLM_MODEL, VLM_PROJECTOR, STORY_MODEL, STORY_PROJECTOR)
