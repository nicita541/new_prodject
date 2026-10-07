import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TrashPage } from './TrashPage';
import { BrowserRouter } from 'react-router-dom';
import * as client from '../api/client';
import * as hooks from '../hooks/useLibrary';

vi.mock('../api/client');
vi.mock('../hooks/useLibrary');

describe('TrashPage', () => {
  const refetch = vi.fn();

  beforeEach(() => {
    vi.mocked(hooks.useLibrary).mockReturnValue({
      data: {
        projects: [],
        trash: {
          projects: [{ id: 'p1', title: 'Trashed Project' }],
          episodes: [{ episode: { id: 'e1', number: 1 }, project_title: 'Trashed Project' }]
        }
      },
      isLoading: false,
      error: null,
      refetch
    } as any);
  });

  it('renders trashed items', () => {
    render(<BrowserRouter><TrashPage /></BrowserRouter>);
    expect(screen.getAllByText('Trashed Project')[0]).toBeInTheDocument();
    expect(screen.getByText('Серия 1')).toBeInTheDocument();
  });

  it('restores project', async () => {
    vi.mocked(client.api.restoreProject).mockResolvedValue({} as any);
    render(<BrowserRouter><TrashPage /></BrowserRouter>);
    
    const restoreBtns = screen.getAllByRole('button', { name: /Восстановить/ });
    await userEvent.click(restoreBtns[0]); // project
    
    expect(client.api.restoreProject).toHaveBeenCalledWith('p1');
    expect(refetch).toHaveBeenCalled();
  });

  it('restores episode', async () => {
    vi.mocked(client.api.restoreEpisode).mockResolvedValue({} as any);
    render(<BrowserRouter><TrashPage /></BrowserRouter>);
    
    const restoreBtns = screen.getAllByRole('button', { name: /Восстановить/ });
    await userEvent.click(restoreBtns[1]); // episode
    
    expect(client.api.restoreEpisode).toHaveBeenCalledWith('e1');
    expect(refetch).toHaveBeenCalled();
  });

  it('renders empty state', () => {
    vi.mocked(hooks.useLibrary).mockReturnValue({
      data: { trash: { projects: [], episodes: [] } },
      isLoading: false,
      error: null
    } as any);
    render(<BrowserRouter><TrashPage /></BrowserRouter>);
    expect(screen.getByText('Корзина пуста.')).toBeInTheDocument();
  });
});
