import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { VideoPlayer } from './VideoPlayer';

describe('VideoPlayer', () => {
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
