import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobProgressPanel } from './JobProgressPanel';
import type { Job } from '../api/types';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../hooks/useJobPolling', () => ({
  useJobPolling: vi.fn()
}));

import { useJobPolling } from '../hooks/useJobPolling';

describe('JobProgressPanel', () => {
  const mockJob = {
    id: 'test-job',
    status: 'running',
    stage: 'extract_audio',
    progress: 0.45,
    message: 'Извлекаем аудио',
    files: []
  } as unknown as Job;

  it('renders running state correctly', () => {
    vi.mocked(useJobPolling).mockReturnValue({ job: mockJob, isLoading: false, error: null } as any);
    render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    
    expect(screen.getByText('Извлекаем аудио')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '0.45');
  });

  it('renders failed state', () => {
    const failedJob: Job = { ...mockJob, status: 'failed', error: 'Network timeout' };
    vi.mocked(useJobPolling).mockReturnValue({ job: failedJob, isLoading: false, error: null } as any);
    render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    
    expect(screen.getByText('Ошибка')).toBeInTheDocument();
    expect(screen.getByText('Network timeout')).toBeInTheDocument();
  });

  it.each([
    ['global_verify', 'Проверка изображения и сюжета', 'analyze'],
    ['quality_gate', 'Проверка качества монтажа', 'plan']
  ])('recognizes production checkpoint %s', (stage, label, group) => {
    vi.mocked(useJobPolling).mockReturnValue({ job: { ...mockJob, stage }, isLoading: false, error: null } as any);
    const { container } = render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    expect(container.querySelector('#stage-label')).toHaveTextContent(label);
    expect(container.querySelector(`[data-stage="${group}"]`)).toHaveAttribute('aria-current', 'step');
    expect(screen.queryByText('Стадия сервера не распознана')).not.toBeInTheDocument();
  });

  it('renders completed state', () => {
    const completedJob: Job = { ...mockJob, status: 'completed' };
    vi.mocked(useJobPolling).mockReturnValue({ job: completedJob, isLoading: false, error: null } as any);
    render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    
    expect(screen.getByText('Монтаж завершён')).toBeInTheDocument();
    expect(screen.getByText('Проверить результат')).toBeInTheDocument();
  });
});
