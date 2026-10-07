import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SourceSelect } from './SourceSelect';
import * as client from '../api/client';

vi.mock('../api/client');

describe('SourceSelect', () => {
  const onChange = vi.fn();
  
  beforeEach(() => {
    vi.mocked(client.api.getSources).mockResolvedValue([
      { id: 's1', name: 'video1.mp4' },
      { id: 's2', name: 'video2.mp4' }
    ] as any);
  });

  it('renders sources and allows selection', async () => {
    render(<SourceSelect episodeId="e1" value="" onChange={onChange} disabled={false} />);
    
    await waitFor(() => {
      expect(screen.getByText('video1.mp4')).toBeInTheDocument();
      expect(screen.getByText('video2.mp4')).toBeInTheDocument();
    });

    const select = screen.getByRole('combobox');
    await userEvent.selectOptions(select, 's2');
    expect(onChange).toHaveBeenCalledWith('s2');
  });


    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(client.api.uploadSource).toHaveBeenCalledWith(file, expect.any(Function));
      expect(onChange).toHaveBeenCalledWith('s3');
    });
  });


    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText('Ошибка загрузки')).toBeInTheDocument();
    });
  });

  it('disables inputs when disabled is true', () => {
    render(<SourceSelect episodeId="e1" value="" onChange={onChange} disabled={true} />);
    expect(screen.getByRole('combobox')).toBeDisabled();
    expect(document.querySelector('input[type="file"]')).toBeDisabled();
  });
});
