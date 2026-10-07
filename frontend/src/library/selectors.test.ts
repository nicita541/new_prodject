import { describe, it, expect } from 'vitest';
import { libraryCopy, p1, p2, e1, e2, completedJob, archivedEpisode } from '../test/fixtures/library';
import { parseLibrarySnapshot } from './contract';
import * as selectors from './selectors';

describe('real backend Library.snapshot contract', () => {
  it('accepts flat projects/episodes and rejects old nested or string-job fixtures', () => {
    const data = libraryCopy();
    expect(Object.keys(data).sort()).toEqual(['episodes', 'projects']);
    expect(() => parseLibrarySnapshot({ projects: [{ ...p1, episodes: [e1] }], trash: {} })).toThrow();
    expect(() => parseLibrarySnapshot({ ...data, episodes: [{ ...e1, jobs: ['job1'] }] })).toThrow();
  });
  it('selects two active episodes and one ready episode of p1', () => {
    const data = libraryCopy();
    expect(selectors.activeProjects(data)).toHaveLength(2);
    expect(selectors.activeEpisodes(data)).toHaveLength(4);
    expect(selectors.episodesForProject(data, p1.id).map(e => e.id)).toEqual([e1.id, e2.id]);
    expect(selectors.completedJobsForEpisode(e1)).toEqual([completedJob]);
    expect(selectors.episodeById(data,e1.id)?.project_id).toBe(p1.id);
  });
  it('matches legacy trash: archived parent hides all its children', () => {
    expect(selectors.archivedProjects(libraryCopy())).toHaveLength(1);
    expect(selectors.archivedEpisodes(libraryCopy()).map(e=>e.id)).toEqual([archivedEpisode.id]);
  });
  it('locks running/queued episodes and chooses running before queued before latest', () => {
    expect(selectors.projectHasRunningJob(libraryCopy(), p1.id)).toBe(true);
    const queued=libraryCopy();queued.episodes[2].jobs[0].status='queued';
    expect(selectors.projectHasRunningJob(queued, p2.id)).toBe(true);
    expect(selectors.episodeHasRunningJob(e1)).toBe(false);
    const data=libraryCopy(), episode=data.episodes[0];
    episode.jobs.push(...e2.jobs, {id:'queued',status:'queued',created_at:'2030-01-01'});
    expect(selectors.activeJobForEpisode(episode)?.status).toBe('running');
    episode.jobs=episode.jobs.filter(job=>job.status!=='running');
    expect(selectors.activeJobForEpisode(episode)?.status).toBe('queued');
    episode.jobs=episode.jobs.filter(job=>job.status!=='queued');
    expect(selectors.activeJobForEpisode(episode)?.status).toBe('failed');
  });
});
