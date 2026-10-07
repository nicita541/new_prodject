import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useJobPolling } from './useJobPolling';
import * as client from '../api/client';

vi.mock('../api/client', () => ({ api: { getJob: vi.fn() } }));

describe('useJobPolling', () => {
  it('does not poll if no jobId', () => {
    const { result } = renderHook(() => useJobPolling(null));
    expect(result.current.job).toBeNull();
  });
});