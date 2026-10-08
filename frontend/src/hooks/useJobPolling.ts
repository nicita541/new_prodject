import { useState, useEffect, useRef } from 'react';
import { api } from '../api/client';
import type { Job } from '../api/types';

export function useJobPolling(jobId: string | null) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setIsPolling(false);
      return;
    }

    let mounted = true;

    const poll = async () => {
      try {
        const data = await api.getJob(jobId);
        if (!mounted) return;
        // Compatibility with a server already processing a video while this
        // UI is upgraded. Its read-only publisher never changes worker state.
        if (!data.stage_progress && data.status !== 'queued') {
          try {
            const snapshot = await api.getLiveStageProgress(jobId);
            const age = Date.now() - Date.parse(snapshot.updated_at);
            if (snapshot.version === 1 && snapshot.job_id === data.id &&
                snapshot.stage === data.stage && snapshot.status === data.status &&
                typeof snapshot.job_updated_at === 'string' &&
                snapshot.job_updated_at === data.updated_at &&
                Number.isFinite(age) && age >= -5000 &&
                (data.status !== 'running' || age < 20000) &&
                snapshot.stage_progress && typeof snapshot.stage_progress === 'object' &&
                !Array.isArray(snapshot.stage_progress)) {
              data.stage_progress = snapshot.stage_progress;
            }
          } catch {
            // An older server without a live publisher still has valid job
            // state; its current stage is shown without a made-up percentage.
          }
        }
        if (!mounted) return;
        
        setJob(data);
        setError(null);

        if (data.status === 'queued' || data.status === 'running') {
          setIsPolling(true);
          timerRef.current = window.setTimeout(poll, 1000);
        } else {
          setIsPolling(false);
        }
      } catch (err) {
        if (!mounted) return;
        setError(err instanceof Error ? err : new Error('Polling failed'));
        setIsPolling(false);
      }
    };

    poll();

    return () => {
      mounted = false;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, [jobId]);

  return { job, error, isPolling };
}
