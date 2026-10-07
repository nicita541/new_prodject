import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useJobPolling } from './useJobPolling';

vi.mock('../api/client', () => ({ api: { getJob: vi.fn() } }));

describe('useJobPolling', () => {
  it('does not poll if no jobId', () => {
    const { result } = renderHook(() => useJobPolling(null));
    expect(result.current.job).toBeNull();
  });
});
