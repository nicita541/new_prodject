import { describe, expect, it } from 'vitest';
import { parseLibrarySnapshot } from './contract';
import { libraryCopy } from '../test/fixtures/library';

describe('backend Library.snapshot contract', () => {
  it('accepts the backend-generated flat snapshot and object job references', () => {
    const snapshot = libraryCopy();
    expect(parseLibrarySnapshot(snapshot)).toBe(snapshot);
    expect(snapshot.episodes[0].jobs[0].id).toEqual(expect.any(String));
  });
  it('rejects the old nested-project/trash payload', () => {
    expect(() => parseLibrarySnapshot({ projects: [], trash: { projects: [], episodes: [] } })).toThrow();
  });
  it('rejects string job IDs and unrecognized job statuses', () => {
    const snapshot = libraryCopy();
    const episode = snapshot.episodes.find(item => item.jobs.length)!;
    expect(() => parseLibrarySnapshot({ ...snapshot, episodes: [{ ...episode, jobs: ['job1'] }] })).toThrow();
    expect(() => parseLibrarySnapshot({ ...snapshot, episodes: [{ ...episode, jobs: [{ ...episode.jobs[0], status: 'ready' }] }] })).toThrow();
  });
});
