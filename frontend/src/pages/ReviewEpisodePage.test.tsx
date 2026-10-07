import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ReviewEpisodePage } from './ReviewEpisodePage';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import * as hooks from '../hooks/useLibrary';
import * as client from '../api/client';

vi.mock('../hooks/useLibrary');
vi.mock('../api/client');

describe('ReviewEpisodePage', () => {
  const mockEpisode = { id: 'ep1', number: 1, jobs: ['job1', 'job2'] };
  const mockData = { projects: [{ id: 'p1', title: 'P1', episodes: [mockEpisode] }], trash: { projects: [], episodes: [] } };

  beforeEach(() => {
    vi.mocked(hooks.useLibrary).mockReturnValue({ data: mockData, isLoading: false, error: null } as any);
  });

  it('renders "Серия не найдена" if missing', () => {
    vi.mocked(hooks.useLibrary).mockReturnValue({ data: null, isLoading: false, error: 'err' } as any);
    render(
      <MemoryRouter initialEntries={['/episode/ep1/review']}>
        <Routes>
          <Route path="/episode/:episodeId/review/:jobId?" element={<ReviewEpisodePage />} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByText('Серия не найдена')).toBeInTheDocument();
  });

  it('excludes running and failed jobs and selects latest completed', async () => {
    vi.mocked(client.api.getJob).mockImplementation(async (id) => {
      if (id === 'job1') return { id: 'job1', status: 'running', created_at: '2023-01-01' } as any;
      if (id === 'job2') return { id: 'job2', status: 'completed', created_at: '2023-01-02' } as any;
      if (id === 'job3') return { id: 'job3', status: 'failed', created_at: '2023-01-03' } as any;
      throw new Error();
    });
    vi.mocked(client.api.getJobPlan).mockResolvedValue({ parts: [], source: { duration: 10 } });

    render(
      <MemoryRouter initialEntries={['/episode/ep1/review']}>
        <Routes>
          <Route path="/episode/:episodeId/review/:jobId?" element={<ReviewEpisodePage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      // job2 is completed, it should be selected, job3 is failed, job1 is running.
      // So there's only 1 option in select.
      const options = screen.getAllByRole('option');
      expect(options).toHaveLength(2); // "Загрузка..." is option 0 when loading, or 1 option when ready?
      // actually "Загрузка" is disabled. The other is "Последний монтаж".
      expect(screen.getByText(/Последний монтаж/)).toBeInTheDocument();
    });
  });

  it('rejects foreign job', async () => {
    // URL jobId is 'foreignJob' which is not in episode.jobs
    render(
      <MemoryRouter initialEntries={['/episode/ep1/review/foreignJob']}>
        <Routes>
          <Route path="/episode/:episodeId/review/:jobId?" element={<ReviewEpisodePage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Монтаж не принадлежит данной серии')).toBeInTheDocument();
    });
  });

  it('displays error if no completed jobs', async () => {
    vi.mocked(client.api.getJob).mockImplementation(async (id) => {
      return { id, status: 'failed', created_at: '2023-01-01' } as any;
    });

    render(
      <MemoryRouter initialEntries={['/episode/ep1/review']}>
        <Routes>
          <Route path="/episode/:episodeId/review/:jobId?" element={<ReviewEpisodePage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Нет завершённых монтажей для проверки')).toBeInTheDocument();
    });
  });

  it('handles plan request failure', async () => {
    vi.mocked(client.api.getJob).mockResolvedValue({ id: 'job1', status: 'completed', created_at: '2023-01-01' } as any);
    vi.mocked(client.api.getJobPlan).mockRejectedValue(new Error('Plan boom'));

    render(
      <MemoryRouter initialEntries={['/episode/ep1/review/job1']}>
        <Routes>
          <Route path="/episode/:episodeId/review/:jobId?" element={<ReviewEpisodePage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Plan boom')).toBeInTheDocument();
    });
  });
});
