import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EpisodesPage } from './EpisodesPage';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import * as client from '../api/client';
import * as hooks from '../hooks/useLibrary';

vi.mock('../api/client');
vi.mock('../hooks/useLibrary');

describe('EpisodesPage', () => {
  const mockProject = {
    id: 'p1',
    title: 'Project 1',
    episodes: [
      { id: 'e1', number: 1, jobs: [] },
      { id: 'e2', number: 2, jobs: ['job1'] }
    ]
  };

  const refetch = vi.fn();

  beforeEach(() => {
    vi.mocked(hooks.useLibrary).mockReturnValue({
      data: { projects: [mockProject] },
      isLoading: false,
      error: null,
      refetch
    } as any);
  });

  const renderPage = () => render(
    <MemoryRouter initialEntries={['/project/p1']}>
      <Routes>
        <Route path="/project/:projectId" element={<EpisodesPage />} />
      </Routes>
    </MemoryRouter>
  );

  it('renders episodes list', () => {
    renderPage();
    expect(screen.getByText('Серия 1')).toBeInTheDocument();
    expect(screen.getByText('Серия 2')).toBeInTheDocument();
  });

  it('creates episode', async () => {
    vi.mocked(client.api.createEpisode).mockResolvedValue({} as any);
    renderPage();
    
    await userEvent.click(screen.getByText(/Создать/i));
    expect(client.api.createEpisode).toHaveBeenCalledWith('p1');
    expect(refetch).toHaveBeenCalled();
  });

  it('deletes episode safely', async () => {
    vi.mocked(client.api.deleteEpisode).mockResolvedValue({} as any);
    window.confirm = vi.fn().mockReturnValue(true);

    renderPage();
    
    const delBtns = screen.getAllByRole('button', { name: /Удалить/ });
    await userEvent.click(delBtns[0]); // delete episode 1

    await waitFor(() => {
      expect(client.api.deleteEpisode).toHaveBeenCalledWith('e1');
    });
    expect(refetch).toHaveBeenCalled();
  });

  it('shows review link if job exists', () => {
    renderPage();
    // e1 has no jobs -> no link
    // e2 has job1 -> review link
    expect(screen.getByText('Посмотреть результаты')).toBeInTheDocument();
  });
});
