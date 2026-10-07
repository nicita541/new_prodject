import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import type { LibrarySnapshot } from '../api/types';

export function useLibrary() {
  const [data, setData] = useState<LibrarySnapshot | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchLibrary = useCallback(async () => {
    try {
      setIsLoading(true);
      const snapshot = await api.getLibrary();
      setData(snapshot);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch library'));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLibrary();
  }, [fetchLibrary]);

  return {
    data,
    error,
    isLoading,
    refetch: fetchLibrary,
  };
}
