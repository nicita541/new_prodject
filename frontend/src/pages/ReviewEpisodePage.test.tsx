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

  it('selects latest completed job when no jobId in URL', async () => {
    vi.mocked(client.api.getJob).mockImplementation(async (id) => {
      if (id === 'job1') return { id: 'job1', status: 'failed' } as any;
      if (id === 'job2') return { id: 'job2', status: 'completed' } as any;
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
      expect(screen.getByText(/Монтаж 2/)).toBeInTheDocument();
    });
  });
});
