import type { LibraryEpisode, LibraryJobRef, LibrarySnapshot } from '../api/types';

export const projectById = (snapshot: LibrarySnapshot | null, id?: string) =>
  snapshot?.projects.find(project => project.id === id);
export const episodeById = (snapshot: LibrarySnapshot | null, id?: string) =>
  snapshot?.episodes.find(episode => episode.id === id);
export const activeProjects = (snapshot: LibrarySnapshot | null) =>
  snapshot?.projects.filter(project => !project.archived_at) ?? [];
export const activeEpisodes = (snapshot: LibrarySnapshot | null) =>
  snapshot?.episodes.filter(episode => !episode.archived_at &&
    activeProjects(snapshot).some(project => project.id === episode.project_id)) ?? [];
export const episodesForProject = (snapshot: LibrarySnapshot | null, id?: string) =>
  activeEpisodes(snapshot).filter(episode => episode.project_id === id).sort((a, b) => a.number - b.number);
export const archivedProjects = (snapshot: LibrarySnapshot | null) =>
  snapshot?.projects.filter(project => !!project.archived_at) ?? [];
// Legacy shows children of an archived project through the project entry only.
export const archivedEpisodes = (snapshot: LibrarySnapshot | null) =>
  snapshot?.episodes.filter(episode => !!episode.archived_at &&
    activeProjects(snapshot).some(project => project.id === episode.project_id)) ?? [];
export const jobsForEpisode = (episode?: LibraryEpisode) =>
  [...(episode?.jobs ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at) || a.id.localeCompare(b.id));
export const completedJobsForEpisode = (episode?: LibraryEpisode) =>
  jobsForEpisode(episode).filter(job => job.status === 'completed');
export const episodeHasRunningJob = (episode?: LibraryEpisode) =>
  jobsForEpisode(episode).some(job => job.status === 'running' || job.status === 'queued');
export const projectHasRunningJob = (snapshot: LibrarySnapshot | null, id?: string) =>
  episodesForProject(snapshot, id).some(episodeHasRunningJob);
export const activeJobForEpisode = (episode?: LibraryEpisode): LibraryJobRef | undefined => {
  const jobs = jobsForEpisode(episode);
  return jobs.find(job => job.status === 'running') ?? jobs.find(job => job.status === 'queued') ?? jobs[0];
};
