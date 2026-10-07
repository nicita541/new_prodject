import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import App from '../App';

vi.mock('../hooks/useLibrary', () => ({
  useLibrary: () => ({ data: null, isLoading: true, error: null })
}));

describe('App Routing backward compatibility', () => {
  let locationReplaceSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    locationReplaceSpy = vi.spyOn(window.location, 'replace').mockImplementation(() => {});
  });

  afterEach(() => {
    locationReplaceSpy.mockRestore();
    window.location.hash = '';
  });

  it('translates /#projects to /projects', () => {
    window.location.hash = '#projects';
    render(<App />);
    expect(locationReplaceSpy).toHaveBeenCalledWith('/projects');
  });

  it('translates /#trash to /trash', () => {
    window.location.hash = '#trash';
    render(<App />);
    expect(locationReplaceSpy).toHaveBeenCalledWith('/trash');
  });

  it('translates /#project/123 to /project/123', () => {
    window.location.hash = '#project/123';
    render(<App />);
    expect(locationReplaceSpy).toHaveBeenCalledWith('/project/123');
  });

  it('translates /#episode/123/edit to /episode/123/edit', () => {
    window.location.hash = '#episode/123/edit';
    render(<App />);
    expect(locationReplaceSpy).toHaveBeenCalledWith('/episode/123/edit');
  });

  it('translates /#episode/123/review/job to /episode/123/review/job', () => {
    window.location.hash = '#episode/123/review/job';
    render(<App />);
    expect(locationReplaceSpy).toHaveBeenCalledWith('/episode/123/review/job');
  });
});
