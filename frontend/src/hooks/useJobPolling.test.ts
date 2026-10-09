import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useJobPolling } from './useJobPolling';
import { api } from '../api/client';
import type { Job, LiveStageProgress } from '../api/types';

vi.mock('../api/client', () => ({ api: { getJob: vi.fn(), getLiveStageProgress: vi.fn() } }));

const legacyJob = { id: 'job-1', status: 'running', stage: 'scenes', progress: .21,
  updated_at: '2026-10-08T16:00:00Z' } as Job;
const snapshot = (): LiveStageProgress => ({ version: 1, job_id: 'job-1', status: 'running',
  stage: 'scenes', updated_at: new Date().toISOString(), job_updated_at: legacyJob.updated_at!,
  stage_progress: { scenes: { status: 'running', fraction: .125, completed: 1, total: 8 } } });

describe('useJobPolling', () => {
  beforeEach(() => { vi.resetAllMocks(); });
  it('recovers after a temporary server error without manual refresh', async () => {
    vi.mocked(api.getJob).mockRejectedValueOnce(new Error('Temporary network failure'))
      .mockResolvedValue({ ...legacyJob, stage_progress: snapshot().stage_progress });
    const { result, unmount } = renderHook(() => useJobPolling('job-1'));
    try {
      await waitFor(() => expect(result.current.error?.message).toBe('Temporary network failure'));
      expect(result.current.isPolling).toBe(true);
      await waitFor(() => expect(result.current.job?.id).toBe('job-1'), { timeout: 3000 });
      expect(result.current.error).toBeNull();
      expect(api.getJob).toHaveBeenCalledTimes(2);
    } finally {
      unmount();
    }
  });

  it('does not poll if no jobId', () => {
    const { result } = renderHook(() => useJobPolling(null));
    expect(result.current.job).toBeNull();
  });

  it('resumes polling a failed job with the same ID after retry and observes completion', async () => {
    vi.mocked(api.getJob).mockResolvedValue({ ...legacyJob, status: 'failed', error: 'Previous attempt',
      stage_progress: snapshot().stage_progress });
    const { result, unmount } = renderHook(() => useJobPolling('job-1'));
    await waitFor(() => expect(result.current.job?.status).toBe('failed'));
    expect(result.current.isPolling).toBe(false);

    vi.mocked(api.getJob).mockResolvedValue({ ...legacyJob, error: null,
      stage_progress: snapshot().stage_progress });
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.job?.status).toBe('running'));
    expect(result.current.job?.error).toBeNull();
    expect(result.current.isPolling).toBe(true);

    vi.mocked(api.getJob).mockResolvedValue({ ...legacyJob, status: 'completed', stage: 'completed',
      stage_progress: snapshot().stage_progress });
    await waitFor(() => expect(result.current.job?.status).toBe('completed'), { timeout: 2500 });
    expect(result.current.isPolling).toBe(false);
    unmount();
  });

  it('merges real live stage counters for an already running server', async () => {
    vi.mocked(api.getJob).mockResolvedValue({ ...legacyJob });
    vi.mocked(api.getLiveStageProgress).mockResolvedValue(snapshot());
    const { result, unmount } = renderHook(() => useJobPolling('job-1'));
    await waitFor(() => expect(result.current.job?.stage_progress?.scenes.fraction).toBe(.125));
    expect(result.current.isPolling).toBe(true);
    unmount();
  });

  it.each([
    { job_id: 'other-job' }, { stage: 'rendering' }, { status: 'failed' as const },
    { job_updated_at: 'older-attempt' }, { updated_at: new Date(Date.now() - 60000).toISOString() }
  ])('rejects mismatched or stale live metadata %j', async change => {
    vi.mocked(api.getJob).mockResolvedValue({ ...legacyJob });
    vi.mocked(api.getLiveStageProgress).mockResolvedValue({ ...snapshot(), ...change });
    const { result, unmount } = renderHook(() => useJobPolling('job-1'));
    await waitFor(() => expect(result.current.job?.id).toBe('job-1'));
    expect(result.current.job?.stage_progress).toBeUndefined();
    unmount();
  });

  it('keeps the terminal snapshot without needing an agent or a live publisher', async () => {
    vi.mocked(api.getJob).mockResolvedValue({ ...legacyJob, status: 'completed', stage: 'completed' });
    vi.mocked(api.getLiveStageProgress).mockResolvedValue({ ...snapshot(), status: 'completed', stage: 'completed',
      updated_at: '2026-10-08T16:00:00Z', stage_progress: { scenes: { status: 'completed', fraction: 1 } } });
    const { result, unmount } = renderHook(() => useJobPolling('job-1'));
    await waitFor(() => expect(result.current.job?.stage_progress?.scenes.fraction).toBe(1));
    expect(result.current.isPolling).toBe(false);
    unmount();
  });

  it('uses normal API counters without the compatibility publisher', async () => {
    vi.mocked(api.getJob).mockResolvedValue({ ...legacyJob, stage_progress: snapshot().stage_progress });
    const { result, unmount } = renderHook(() => useJobPolling('job-1'));
    await waitFor(() => expect(result.current.job?.id).toBe('job-1'));
    expect(api.getLiveStageProgress).not.toHaveBeenCalled();
    unmount();
  });

  it('continues job polling if compatibility metadata is unavailable', async () => {
    vi.mocked(api.getJob).mockResolvedValue({ ...legacyJob });
    vi.mocked(api.getLiveStageProgress).mockRejectedValue(new Error('404'));
    const { result, unmount } = renderHook(() => useJobPolling('job-1'));
    await waitFor(() => expect(result.current.job?.id).toBe('job-1'));
    expect(result.current.error).toBeNull();
    expect(result.current.isPolling).toBe(true);
    unmount();
  });
});
