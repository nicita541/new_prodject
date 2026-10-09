import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { VideoPlayer } from './VideoPlayer';

describe('VideoPlayer', () => {
  it('advances only when a next file exists and resumes playback', () => {
    const play = vi.spyOn(window.HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    try {
      const ended = vi.fn();
      const { container, rerender } = render(<VideoPlayer file={{ url: '/one.mp4' } as any} onEnded={ended} />);
      const video = container.querySelector('video')!;
      expect(video.loop).toBe(false);
      fireEvent.ended(video);
      expect(ended).toHaveBeenCalledOnce();
      rerender(<VideoPlayer file={{ url: '/two.mp4' } as any} />);
      expect(video.src).toMatch(/\/two\.mp4$/);
      expect(play).toHaveBeenCalledOnce();
      fireEvent.ended(video);
      expect(ended).toHaveBeenCalledOnce();
    } finally {
      play.mockRestore();
    }
  });

  it('renders without src if no file', () => {
    const { container } = render(<VideoPlayer file={undefined} />);
    const video = container.querySelector('video') as HTMLVideoElement;
    expect(video).toBeInTheDocument();
    expect(video.getAttribute('src')).toBeNull();
  });

  it('renders correct src for file', () => {
    const { container } = render(<VideoPlayer file={{ url: '/test.mp4' } as any} />);
    const video = container.querySelector('video') as HTMLVideoElement;
    expect(video.src).toMatch(/\/test\.mp4$/);
  });

  it('updates src when file changes', () => {
    const { container, rerender } = render(<VideoPlayer file={{ url: '/test1.mp4' } as any} />);
    const video = container.querySelector('video') as HTMLVideoElement;
    expect(video.src).toMatch(/\/test1\.mp4$/);

    rerender(<VideoPlayer file={{ url: '/test2.mp4' } as any} />);
    expect(video.src).toMatch(/\/test2\.mp4$/);
  });
});
