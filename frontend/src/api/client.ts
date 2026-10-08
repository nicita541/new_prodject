import type {
  Job,
  LiveStageProgress,
  Plan,
  Source,
  MusicSettings,
  DeepSeekStatus,
  DeepSeekCheck,
  LibrarySnapshot,
  LibraryProject,
  EpisodeRecord,
  ArchiveResponse,
  MusicSettingsRequest,
  HealthStatus,
  EpisodeSettings,
  ResetBudgetResponse
} from './types';
import { parseLibrarySnapshot } from '../library/contract';

export class ApiError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', ...options });
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError('Сервер вернул неожиданный ответ.', response.status);
  }
  
  if (!response.ok) {
    const errorBody = body as { detail?: string | unknown, message?: string };
    const message = errorBody.detail ?? errorBody.message;
    throw new ApiError(
      typeof message === 'string' ? message : `Ошибка сервера (${response.status}).`,
      response.status
    );
  }
  return body as T;
}

export const api = {
  getHealth: () => fetchApi<HealthStatus>('/api/health'),
  
  // Library
  getLibrary: (): Promise<LibrarySnapshot> => fetchApi<unknown>('/api/library').then(parseLibrarySnapshot),
  createProject: (title: string) => fetchApi<LibraryProject>('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  }),
  createEpisode: (projectId: string, number?: number) => fetchApi<EpisodeRecord>(`/api/projects/${projectId}/episodes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ number: number ?? null }),
  }),
  deleteProject: (id: string) => fetchApi<ArchiveResponse>(`/api/projects/${id}`, { method: 'DELETE' }),
  deleteEpisode: (id: string) => fetchApi<ArchiveResponse>(`/api/episodes/${id}`, { method: 'DELETE' }),
  restoreProject: (id: string) => fetchApi<ArchiveResponse>(`/api/projects/${id}/restore`, { method: 'POST' }),
  restoreEpisode: (id: string) => fetchApi<ArchiveResponse>(`/api/episodes/${id}/restore`, { method: 'POST' }),
  saveEpisodeSettings: (id: string, settings: EpisodeSettings) => fetchApi<EpisodeRecord>(`/api/episodes/${id}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  }),
  launchEpisodeJob: (id: string) => fetchApi<Job>(`/api/episodes/${id}/jobs`, { method: 'POST' }),

  // Sources
  getSources: () => fetchApi<Source[]>('/api/sources'),
  
  // Jobs
  getJobs: () => fetchApi<Job[]>('/api/jobs'),
  getJob: (id: string) => fetchApi<Job>(`/api/jobs/${id}`),
  getLiveStageProgress: (id: string) => fetchApi<LiveStageProgress>(`/assets/job-progress/${id}.json`),
  cancelJob: (id: string) => fetchApi<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  retryJob: (id: string) => fetchApi<Job>(`/api/jobs/${id}/retry`, { method: 'POST' }),
  getJobPlan: (id: string) => fetchApi<Plan>(`/api/jobs/${id}/plan`),
  resetJobBudget: (id: string) => fetchApi<ResetBudgetResponse>(`/api/jobs/${id}/reset-budget`, { method: 'POST' }),
  openJobFolder: (id: string) => fetchApi<{opened: boolean, path: string}>(`/api/jobs/${id}/open-folder`, { method: 'POST' }),
  saveVideos: (id: string, all: boolean, filename?: string) => fetchApi<{cancelled: boolean, count: number, files: string[]}>(`/api/jobs/${id}/save-videos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(all ? { all: true } : { filename }),
  }),
  
  // Settings
  getMusicSettings: () => fetchApi<MusicSettings>('/api/music'),
  saveMusicSettings: (settings: MusicSettingsRequest) => fetchApi<MusicSettings>('/api/music', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  }),
  openMusicFolder: () => fetchApi<{opened: boolean, path: string}>('/api/music/open', { method: 'POST' }),
  
  // DeepSeek
  getDeepSeekStatus: () => fetchApi<DeepSeekStatus>('/api/deepseek'),
  checkDeepSeek: () => fetchApi<DeepSeekCheck>('/api/deepseek/check', { method: 'POST' }),
};
