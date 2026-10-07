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
