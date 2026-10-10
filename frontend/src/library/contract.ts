import type { LibrarySnapshot } from '../api/types';

const statuses = new Set(['queued', 'running', 'completed', 'failed', 'cancelled', 'interrupted']);
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const archived = (value: Record<string, unknown>) =>
  value.archived_at == null || typeof value.archived_at === 'string';

export function parseLibrarySnapshot(value: unknown): LibrarySnapshot {
  if (!object(value) || !Array.isArray(value.projects) || !Array.isArray(value.episodes) ||
      value.projects.some(project => !object(project) || typeof project.id !== 'string' ||
        typeof project.title !== 'string' || typeof project.created_at !== 'string' || !archived(project)) ||
      value.episodes.some(episode => !object(episode) || typeof episode.id !== 'string' ||
        typeof episode.project_id !== 'string' || !Number.isInteger(episode.number) ||
        typeof episode.title !== 'string' || typeof episode.created_at !== 'string' || !archived(episode) ||
        !(episode.source_id === null || typeof episode.source_id === 'string') || !object(episode.settings) ||
        !['portrait', 'cinema'].includes(String(episode.settings.layout)) ||
        !['classic', 'accent'].includes(String(episode.settings.caption_style)) ||
        !['local', 'deepseek', 'hybrid', 'deepseek_plan', 'local_flash_story'].includes(String(episode.settings.analysis_provider)) ||
        !Array.isArray(episode.jobs) || episode.jobs.some(job => !object(job) || typeof job.id !== 'string' ||
          typeof job.created_at !== 'string' || !statuses.has(String(job.status))))) {
    throw new Error('Сервер вернул некорректную структуру библиотеки.');
  }
  return value as unknown as LibrarySnapshot;
}
