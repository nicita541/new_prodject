import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { JobProgressPanel } from './JobProgressPanel';
import type { Job } from '../api/types';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../hooks/useJobPolling', () => ({
  useJobPolling: vi.fn()
}));

import { useJobPolling } from '../hooks/useJobPolling';
import { api } from '../api/client';

const mockPolling = (value: Omit<ReturnType<typeof useJobPolling>, 'refresh'>) =>
  vi.mocked(useJobPolling).mockReturnValue({ ...value, refresh: vi.fn() });

describe('JobProgressPanel', () => {
  const mockJob = {
    id: 'test-job',
    status: 'running',
    stage: 'extract_audio',
    progress: 0.45,
    message: 'Извлекаем аудио',
    files: []
  } as unknown as Job;

  const pendingSteps = (): NonNullable<Job['stage_progress']> => ({
    prepare: { status: 'pending', fraction: 0 },
    transcribe: { status: 'pending', fraction: 0 },
    scenes: { status: 'pending', fraction: 0 },
    analyze: { status: 'pending', fraction: 0 },
    condense: { status: 'pending', fraction: 0 },
    framing: { status: 'pending', fraction: 0 },
    plan: { status: 'pending', fraction: 0 },
    render: { status: 'pending', fraction: 0 }
  });

  it('renders running state correctly', () => {
    mockPolling({ job: mockJob, isLoading: false, error: null } as any);
    render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    
    expect(screen.getByText('Извлекаем аудио')).toBeInTheDocument();
    expect(screen.queryByText('45%')).not.toBeInTheDocument();
    expect(document.querySelector('#job-progress')).toBeNull();
    expect(document.querySelector('#progress-label')).toBeNull();
  });

  it('renders failed state', () => {
    const failedJob: Job = { ...mockJob, status: 'failed', error: 'Network timeout' };
    mockPolling({ job: failedJob, isLoading: false, error: null } as any);
    render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    
    expect(screen.getByText('Ошибка')).toBeInTheDocument();
    expect(screen.getByText('Network timeout')).toBeInTheDocument();
  });

  it('restarts progress polling after a successful retry', async () => {
    const failedJob: Job = { ...mockJob, status: 'failed' };
    const refresh = vi.fn();
    vi.mocked(useJobPolling).mockReturnValue({ job: failedJob, isPolling: false, error: null, refresh });
    const retry = vi.spyOn(api, 'retryJob').mockResolvedValue({ ...failedJob, status: 'running' });
    try {
      render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
      await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
      expect(retry).toHaveBeenCalledWith('test-job');
    } finally {
      retry.mockRestore();
    }
  });

  it('uses neutral styling for a normal processing message', () => {
    mockPolling({ job: mockJob, isPolling: true, error: null });
    render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    expect(screen.getByRole('status')).toHaveClass('notice');
    expect(screen.getByRole('status')).not.toHaveClass('message');
  });

  it.each([
    ['local', 'На компьютере'], ['deepseek_plan', 'DeepSeek']
  ] as const)('shows the actual job provider %s independently of episode settings', (provider, label) => {
    mockPolling({
      job: { ...mockJob, analysis_provider: provider }, isPolling: true, error: null
    });
    render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    expect(screen.getByText(`Этот запуск: ${label}`)).toBeInTheDocument();
  });

  it('keeps checkpoints pending while the running worker is still queued', () => {
    mockPolling({
      job: { ...mockJob, stage: 'queued', progress: 0, message: 'Запуск обработки' },
      isPolling: true, error: null
    });
    const { container } = render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    expect(screen.queryByText('Стадия сервера не распознана')).not.toBeInTheDocument();
    expect(container.querySelectorAll('.stage-item.pending')).toHaveLength(8);
    expect(container.querySelector('[aria-current="step"]')).toBeNull();
  });

  it.each([
    [0.19, 'Определение смены планов'],
    [0.21, 'Объединение планов в смысловые сцены']
  ])('shows scene detection after completed preparation and transcription at %s', (progress, message) => {
    mockPolling({
      job: { ...mockJob, stage: 'scenes', progress, message }, isPolling: true, error: null
    });
    render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);

    expect(screen.queryByText(`${Math.round(progress * 100)}%`)).not.toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
    for (const label of ['Подготовка видео', 'Распознавание русской речи']) {
      const checkpoint = screen.getByText(label).closest('li')!;
      expect(within(checkpoint).getByText('Готово')).toBeInTheDocument();
      expect(checkpoint).not.toHaveAttribute('aria-current');
    }
    const scenes = screen.getAllByText('Поиск смысловых сцен').find(node => node.closest('li'))!.closest('li')!;
    expect(scenes).toHaveAttribute('aria-current', 'step');
    expect(within(scenes).getByText('Выполняется')).toBeInTheDocument();
    expect(within(scenes).getByRole('progressbar')).not.toHaveAttribute('value');
    const analysis = screen.getByText('Анализ сюжета и изображения').closest('li')!;
    expect(within(analysis).getByText('Ожидает')).toBeInTheDocument();
    const rendering = screen.getByText('Экспорт частей').closest('li')!;
    expect(within(rendering).getByText('Ожидает')).toBeInTheDocument();
  });

  it.each([
    ['global_verify', 'Проверка изображения и сюжета', 'analyze'],
    ['quality_gate', 'Проверка качества монтажа', 'plan']
  ])('recognizes production checkpoint %s', (stage, label, group) => {
    mockPolling({ job: { ...mockJob, stage }, isLoading: false, error: null } as any);
    const { container } = render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    expect(container.querySelector('#stage-label')).toHaveTextContent(label);
    expect(container.querySelector(`[data-stage="${group}"]`)).toHaveAttribute('aria-current', 'step');
    expect(screen.queryByText('Стадия сервера не распознана')).not.toBeInTheDocument();
  });

  it('uses authoritative scene progress instead of the overall job stage and percentage', () => {
    mockPolling({
      job: { ...mockJob, stage: 'rendering', progress: 0.83, stage_progress: {
        ...pendingSteps(),
        prepare: { status: 'completed', fraction: 1 },
        transcribe: { status: 'completed', fraction: 1 },
        scenes: { status: 'running', fraction: 0.375, completed: 3, total: 8,
          phase: 'Проверка границ сцен', detail: 'Сравниваем соседние планы' }
      } }, isPolling: true, error: null
    });
    const { container } = render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    const scenes = container.querySelector<HTMLElement>('[data-stage="scenes"]')!;
    expect(scenes).toHaveAttribute('aria-current', 'step');
    expect(within(scenes).getByRole('progressbar')).toHaveAttribute('value', '0.375');
    expect(within(scenes).getByText('38%')).toBeInTheDocument();
    expect(screen.getByText('3 из 8')).toBeInTheDocument();
    expect(screen.getByText('Проверка границ сцен')).toBeInTheDocument();
    expect(screen.getByText('Сравниваем соседние планы')).toBeInTheDocument();
    expect(screen.queryByText('83%')).not.toBeInTheDocument();
    expect(container.querySelector('[data-stage="render"]')).toHaveClass('pending');
    expect(container.querySelectorAll('.stage-item.done')).toHaveLength(2);
  });

  it('keeps an unknown fraction indeterminate and does not derive it from counts or overall progress', () => {
    mockPolling({
      job: { ...mockJob, stage: 'analyze', progress: 0.45, stage_progress: {
        ...pendingSteps(), analyze: { status: 'running', fraction: null, completed: 2, total: 10 }
      } }, isPolling: true, error: null
    });
    const { container } = render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    const analysis = container.querySelector<HTMLElement>('[data-stage="analyze"]')!;
    expect(within(analysis).getByRole('progressbar')).not.toHaveAttribute('value');
    expect(within(analysis).getByText('Выполняется')).toBeInTheDocument();
    expect(within(analysis).getByText('2 из 10')).toBeInTheDocument();
    expect(screen.queryByText('20%')).not.toBeInTheDocument();
    expect(screen.queryByText('45%')).not.toBeInTheDocument();
  });

  it('shows zero processed items and zero stage progress', () => {
    mockPolling({
      job: { ...mockJob, stage: 'scenes', stage_progress: {
        ...pendingSteps(), scenes: { status: 'running', fraction: 0, completed: 0, total: 8 }
      } }, isPolling: true, error: null
    });
    const { container } = render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    const scenes = container.querySelector<HTMLElement>('[data-stage="scenes"]')!;
    expect(within(scenes).getByRole('progressbar')).toHaveAttribute('value', '0');
    expect(within(scenes).getByText('0%')).toBeInTheDocument();
    expect(within(scenes).getByText('0 из 8')).toBeInTheDocument();
  });

  it('shows measurable progress for the first checked boundary out of 1917', () => {
    const fraction = 1 / 1917;
    mockPolling({
      job: { ...mockJob, stage: 'scenes', stage_progress: {
        ...pendingSteps(), scenes: { status: 'running', fraction, completed: 1, total: 1917 }
      } }, isPolling: true, error: null
    });
    const { container } = render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    const scenes = container.querySelector<HTMLElement>('[data-stage="scenes"]')!;
    expect(within(scenes).getByText('0,05%')).toBeInTheDocument();
    expect(within(scenes).queryByText('0%')).not.toBeInTheDocument();
    expect(within(scenes).getByRole('progressbar')).toHaveAttribute('value', String(fraction));
    expect(within(scenes).getByText('1 из 1917')).toBeInTheDocument();
  });

  it('displays a fresh phase when analysis progress resets for another pass', () => {
    const setPass = (fraction: number, phase: string) => mockPolling({
      job: { ...mockJob, stage: 'global_verify', stage_progress: {
        ...pendingSteps(), analyze: { status: 'running', fraction, phase }
      } }, isPolling: true, error: null
    });
    setPass(0.8, 'Первичный анализ сцен');
    const { rerender } = render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    expect(screen.getByText('80%')).toBeInTheDocument();
    expect(screen.getByText('Первичный анализ сцен')).toBeInTheDocument();
    setPass(0.1, 'Проверка связности истории');
    rerender(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    expect(screen.getByText('10%')).toBeInTheDocument();
    expect(screen.getByText('Проверка связности истории')).toBeInTheDocument();
    expect(screen.queryByText('Первичный анализ сцен')).not.toBeInTheDocument();
    expect(screen.queryByText('80%')).not.toBeInTheDocument();
  });

  it.each([
    ['failed', 'Остановлено с ошибкой'], ['cancelled', 'Отменено'], ['interrupted', 'Прервано']
  ] as const)('preserves reported partial progress for a %s step', (status, label) => {
    mockPolling({
      job: { ...mockJob, stage: 'analyze', status, stage_progress: {
        ...pendingSteps(), analyze: { status, fraction: 0.4 }
      } }, isPolling: false, error: null
    });
    const { container } = render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    const analysis = container.querySelector<HTMLElement>('[data-stage="analyze"]')!;
    expect(within(analysis).getByText(label)).toBeInTheDocument();
    expect(within(analysis).getByText('40%')).toBeInTheDocument();
    expect(analysis).not.toHaveAttribute('aria-current');
  });

  it('renders completed state', () => {
    const completedJob: Job = { ...mockJob, status: 'completed' };
    mockPolling({ job: completedJob, isLoading: false, error: null } as any);
    render(<BrowserRouter><JobProgressPanel jobId="test-job" episodeId="test-episode" /></BrowserRouter>);
    
    expect(screen.getByText('Монтаж завершён')).toBeInTheDocument();
    expect(screen.getByText('Проверить результат')).toBeInTheDocument();
    expect(screen.getAllByRole('progressbar')).toHaveLength(8);
    for (const progressbar of screen.getAllByRole('progressbar')) {
      expect(progressbar).toHaveAttribute('value', '1');
    }
  });
});
