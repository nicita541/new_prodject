export interface JobFile {
  name: string;
  url: string;
  subtitle_url: string | null;
  duration?: number | null;
}

export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';

export interface Job {
  id: string;
  source_id: string;
  source_name: string;
  status: JobStatus;
  analysis_provider: 'local' | 'deepseek' | 'hybrid' | 'deepseek_plan';
  layout: 'portrait' | 'cinema';
  caption_style: 'classic' | 'accent';
  progress: number;
  stage: string;
  message?: string;
  error?: string | null;
  created_at: string;
  outputs?: string[];
  files?: JobFile[];
  cancel_requested?: boolean;
}

export interface Cut {
  start: number;
  end: number;
}

export interface CoverContext {
  title: string;
  synopsis: string;
  prompt: string;
  method: string;
}

export interface PlanPart {
  cuts: Cut[];
  cover_context?: CoverContext;
  music_track?: string | null;
  index: number;
  duration?: number;
}

export interface TimelineReason {
  kind: string;
  start: number;
  end: number;
  title: string;
  detail: string;
  retained: boolean;
  event_id?: string;
}

export interface DebugTimeline {
  available: boolean;
  reasons?: TimelineReason[];
}

export interface QualitySummary {
  available: boolean;
  warnings: Array<{text: string} | string>;
  notes: Array<{text: string} | string>;
}

export interface Plan {
  source: {
    duration: number;
  };
  parts: PlanPart[];
  debug_timeline?: DebugTimeline;
  quality_summary?: QualitySummary;
  warnings?: string[];
}

export interface Source {
  id: string;
  name: string;
  size: number;
}

export interface MusicSettings {
  enabled: boolean;
  volume: number;
  track: string | null;
  mode: 'random_per_part' | 'single' | 'per_part';
  part_tracks?: Record<string, string | null>;
  tracks?: string[];
  fade_in?: number;
  fade_out?: number;
}

export interface DeepSeekStatus {
  configured: boolean;
  budget_usd: number | null;
  charged_ceiling_usd?: number | null;
  remaining_usd?: number | null;
  model?: string;
}

export interface HealthStatus {
  ready: boolean;
  busy: boolean;
  missing: string[];
}

export interface EpisodeSettings {
  source_id: string;
  layout?: 'portrait' | 'cinema';
  caption_style?: 'classic' | 'accent';
  analysis_provider?: 'local' | 'deepseek' | 'hybrid' | 'deepseek_plan';
}

export interface ResetBudgetResponse {
  accounting_enabled: false;
  attempt: number;
  limit_usd: number | null;
  charged_ceiling_usd: number | null;
  remaining_usd: number | null;
  job_total_usd: number | null;
}

export interface QualityWarningItem {
  text: string;
}

export interface DeepSeekCheck {
  available: boolean;
  model: string;
  vision_supported: boolean | null;
  balance_infos: Array<{ currency: string; total_balance: string | number }>;
}

export interface LibraryJobRef {
  id: string;
  status: JobStatus;
  created_at: string;
}

export interface LibraryEpisode {
  id: string;
  project_id: string;
  number: number;
  title: string;
  source_id: string | null;
  settings: {
    layout: 'portrait' | 'cinema';
    caption_style: 'classic' | 'accent';
    analysis_provider: 'local' | 'deepseek' | 'hybrid' | 'deepseek_plan';
  };
  created_at: string;
  archived_at?: string | null;
  jobs: LibraryJobRef[];
}

export interface LibraryProject {
  id: string;
  title: string;
  created_at: string;
  archived_at?: string | null;
}

export interface LibrarySnapshot {
  projects: LibraryProject[];
  episodes: LibraryEpisode[];
}

// Mutation responses contain the stored episode; jobs are added by snapshot().
export type EpisodeRecord = Omit<LibraryEpisode, 'jobs'>;
export interface ArchiveResponse { id: string; archived: boolean }
export interface MusicSettingsRequest {
  enabled: boolean;
  volume: number;
  track?: string | null;
  mode?: MusicSettings['mode'];
  part_tracks?: Record<string, string | null> | null;
}
