import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProjectsPage } from './ProjectsPage';
import { BrowserRouter } from 'react-router-dom';
import * as client from '../api/client';
import * as hooks from '../hooks/useLibrary';

vi.mock('../api/client');
vi.mock('../hooks/useLibrary');

describe('ProjectsPage', () => {
  const mockLibrary = {
    projects: [
      { id: 'p1', title: 'Project 1', episodes: [] },
      { id: 'p2', title: 'Project 2', episodes: [{ id: 'e1' }] }
    ],
    trash: { projects: [], episodes: [] }
  };

  const refetch = vi.fn();

  beforeEach(() => {
    vi.mocked(hooks.useLibrary).mockReturnValue({
      data: mockLibrary,
      isLoading: false,
      error: null,
      refetch
    } as any);
  });

  it('renders list of projects', () => {
    render(<BrowserRouter><ProjectsPage /></BrowserRouter>);
    expect(screen.getByText('Project 1')).toBeInTheDocument();
    expect(screen.getByText('Project 2')).toBeInTheDocument();
  });

  it('creates project', async () => {
    vi.mocked(client.api.createProject).mockResolvedValue({} as any);
    render(<BrowserRouter><ProjectsPage /></BrowserRouter>);
    
    await userEvent.click(screen.getByText(/Создать проект/));
    expect(client.api.createProject).toHaveBeenCalled();
    expect(refetch).toHaveBeenCalled();
  });

  it('deletes project', async () => {
    vi.mocked(client.api.deleteProject).mockResolvedValue({} as any);
    window.confirm = vi.fn().mockReturnValue(true);

    render(<BrowserRouter><ProjectsPage /></BrowserRouter>);
    
    const delBtns = screen.getAllByRole('button', { name: /Удалить/ });
    await userEvent.click(delBtns[0]);

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(client.api.deleteProject).toHaveBeenCalledWith('p1');
    });
    expect(refetch).toHaveBeenCalled();
  });
});
