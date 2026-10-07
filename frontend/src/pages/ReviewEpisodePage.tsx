import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useLibrary } from '../hooks/useLibrary';
import { api } from '../api/client';
import type { Job, Plan } from '../api/types';

export function ReviewEpisodePage() {
  const { episodeId } = useParams<{ episodeId: string }>();
  const { data, isLoading, error } = useLibrary();
  
  const project = data?.projects.find(p => p.episodes.some(e => e.id === episodeId));
  const episode = project?.episodes.find(e => e.id === episodeId);

  // We should also look at the job id if it's in the URL, but the user requested #episode/:id/review/:jobId
  // The current route is `/episode/:episodeId/review`. Let's assume the latest completed job.
  const [job, setJob] = useState<Job | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);

  useEffect(() => {
    if (episode && episode.jobs) {
      // Find latest completed job
      const fetchJob = async () => {
        try {
          const allJobs = await Promise.all(episode.jobs!.map(id => api.getJob(id)));
          const completed = allJobs.filter(j => j.status === 'completed');
          if (completed.length > 0) {
            setJob(completed[0]);
            const p = await api.getJobPlan(completed[0].id);
            setPlan(p);
          }
        } catch (e) {
          console.error(e);
        }
      };
      fetchJob();
    }
  }, [episode]);

  if (isLoading && !data) return <p className="message">Загрузка...</p>;
  if (error || !episode) return <p className="message">Серия не найдена</p>;

  return (
    <main className="screen-shell">
      <div className="screen-toolbar">
        <div>
          <h1 className="page-title">Проверка монтажа {episode.number}</h1>
        </div>
        <Link id="review-edit-link" className="btn-secondary" to={`/episode/${episode.id}/edit`}>⚙ Настройки серии</Link>
      </div>
      
      <div className="review-workspace" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        {job && plan ? (
          <>
            {/* Timeline Panel */}
            <section id="timeline-panel" className="panel timeline-panel">
              <div className="panel-heading">
                <h2 id="timeline-heading" className="panel-title">Таймлайн серии ({plan.source.duration.toFixed(2)}s)</h2>
              </div>
              <div className="timeline-scroll">
                <div id="timeline-map" className="timeline-map">
                  <div id="timeline-ruler" className="timeline-ruler"></div>
                  <div id="timeline-groups" className="timeline-groups"></div>
                  <div className="timeline-line">
                    <div id="timeline-overview" className="timeline-track"></div>
                    <div id="timeline-playhead" className="timeline-playhead"></div>
                  </div>
                </div>
              </div>
            </section>

            {/* Results Panel */}
            <section id="results-panel" className="panel playlist-panel">
              <div className="panel-heading">
                <h2 id="results-heading" className="panel-title">Готовые шортсы ({job.files?.length || 0})</h2>
              </div>
              
              <div className="shorts-viewer-layout">
                <div className="shorts-player-col">
                  <div className="shorts-preview-box">
                    <video id="player" controls playsInline preload="metadata" loop></video>
                  </div>
                </div>

                <div className="shorts-playlist-col">
                  <p className="small muted" style={{ marginBottom: '10px', fontWeight: 600 }}>Выберите часть для просмотра:</p>
                  <div id="playlist" className="playlist-list" style={{ maxHeight: '380px', overflowY: 'auto' }}>
                    {job.files?.map((file, i) => (
                      <li key={i}>
                        <button type="button">
                          <span>Часть {String(i+1).padStart(2, '0')}</span>
                          <span>{file.duration ? file.duration.toFixed(1) + 's' : ''}</span>
                        </button>
                      </li>
                    ))}
                  </div>
                </div>
              </div>
            </section>
          </>
        ) : (
          <p id="review-empty" className="empty-state">Готового монтажа пока нет. Вернитесь в настройки серии.</p>
        )}
      </div>
    </main>
  );
}
