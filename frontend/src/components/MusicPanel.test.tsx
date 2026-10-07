import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MusicPanel } from './MusicPanel';
import * as client from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getMusicSettings: vi.fn(),
    saveMusicSettings: vi.fn(),
    openMusicFolder: vi.fn()
  }
}));

describe('MusicPanel', () => {
  const mockSettings = {
    enabled: true,
    volume: 0.5,
    mode: 'per_part',
    track: null,
    tracks: ['track1.mp3', 'track2.mp3'],
    part_tracks: { '1': 'track1.mp3' }
  };

  beforeEach(() => {
    vi.mocked(client.api.getMusicSettings).mockResolvedValue(mockSettings as any);
  });

  it('renders correctly with 6 parts', async () => {
    render(<MusicPanel partCount={6} />);
    
    await waitFor(() => {
      expect(screen.getByText('Фоновая музыка')).toBeInTheDocument();
    });

    // Should render 6 part selectors
    const partSelectors = screen.getAllByRole('combobox');
    // 1 for mode + 6 for parts = 7
    expect(partSelectors).toHaveLength(7);
  });

  it('saves correctly when changing part track to none', async () => {
    render(<MusicPanel partCount={2} />);
    
    await waitFor(() => {
      expect(screen.getByText('Фоновая музыка')).toBeInTheDocument();
    });

    const selects = screen.getAllByRole('combobox');
    // selects[0] is mode
    // selects[1] is part 1
    // selects[2] is part 2

    // change part 2 to none
    await userEvent.selectOptions(selects[2], 'none');

    expect(client.api.saveMusicSettings).toHaveBeenCalledWith(expect.objectContaining({
      part_tracks: { '1': 'track1.mp3' } // '2' should be deleted (it wasn't there anyway, but make sure it doesn't add 'none')
    }));
  });

  it('saves correctly when changing part track to song', async () => {
    render(<MusicPanel partCount={2} />);
    
    await waitFor(() => {
      expect(screen.getByText('Фоновая музыка')).toBeInTheDocument();
    });

    const selects = screen.getAllByRole('combobox');
    await userEvent.selectOptions(selects[2], 'track2.mp3');

    expect(client.api.saveMusicSettings).toHaveBeenCalledWith(expect.objectContaining({
      part_tracks: { '1': 'track1.mp3', '2': 'track2.mp3' }
    }));
  });
});
