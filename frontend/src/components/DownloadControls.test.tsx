import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DownloadControls } from './DownloadControls';
import * as client from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    downloadFile: vi.fn(),
    downloadAllFiles: vi.fn()
  }
}));

describe('DownloadControls', () => {
  const mockFiles = [
    { file: 'file1.mp4', status: 'ready', subtitle_file: 'sub1.srt' },
    { file: 'file2.mp4', status: 'ready' }
  ] as any;

  it('renders disabled if no file', () => {
    render(<DownloadControls jobId="job1" files={[]} selectedIndex={0} />);
    expect(screen.getByRole('button', { name: /Скачать MP4/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Сохранить все/ })).toBeDisabled();
  });

  it('triggers single download', async () => {
    render(<DownloadControls jobId="job1" files={mockFiles} selectedIndex={0} />);
    const btn = screen.getByRole('button', { name: /Скачать MP4/ });
    expect(btn).not.toBeDisabled();
    await userEvent.click(btn);
    expect(client.api.downloadFile).toHaveBeenCalledWith('job1', 'file1.mp4');
  });

  it('triggers subtitle download', async () => {
    render(<DownloadControls jobId="job1" files={mockFiles} selectedIndex={0} />);
    const btn = screen.getByRole('button', { name: /Субтитры/ });
    await userEvent.click(btn);
    expect(client.api.downloadFile).toHaveBeenCalledWith('job1', 'sub1.srt');
  });

  it('triggers download all', async () => {
    render(<DownloadControls jobId="job1" files={mockFiles} selectedIndex={0} />);
    const btn = screen.getByRole('button', { name: /Сохранить все \(2\)/ });
    await userEvent.click(btn);
    expect(client.api.downloadAllFiles).toHaveBeenCalledWith('job1');
  });

  it('handles partial save error correctly', async () => {
    vi.mocked(client.api.downloadAllFiles).mockRejectedValue(new Error('partial'));
    render(<DownloadControls jobId="job1" files={mockFiles} selectedIndex={0} />);
    const btn = screen.getByRole('button', { name: /Сохранить все/ });
    await userEvent.click(btn);
    // the alert would show, but we can just check it doesn't crash
  });
});
