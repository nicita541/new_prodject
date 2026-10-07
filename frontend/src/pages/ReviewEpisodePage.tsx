import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useLibrary } from '../hooks/useLibrary';
import { api } from '../api/client';
import type { Job, Plan } from '../api/types';
import { VideoPlayer } from '../components/VideoPlayer';
import { Playlist } from '../components/Playlist';
import { DownloadControls } from '../components/DownloadControls';
import { PartContext } from '../components/PartContext';
import { Timeline } from '../components/Timeline';
import { QualityWarnings } from '../components/QualityWarnings';

export function ReviewEpisodePage() {
  const { episodeId, jobId } = useParams<{ episodeId: string, jobId?: string }>();
  const navigate = useNavigate();
  const { data, isLoading, error } = useLibrary();
  
  const project = data?.projects.find(p => p.episodes.some(e => e.id === episodeId));
  const episode = project?.episodes.find(e => e.id === episodeId);

  const [job, setJob] = useState<Job | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    if (episode && episode.jobs) {
      const fetchJob = async () => {
        try {
          let targetJobId = jobId;
          if (!targetJobId) {
            // Find latest completed job
            const allJobs = await Promise.all(episode.jobs!.map(id => api.getJob(id)));
            const completed = allJobs.filter(j => j.status === 'completed');
            if (completed.length > 0) {
              targetJobId = completed[0].id;
            }
          }
          if (targetJobId) {
            const j = await api.getJob(targetJobId);
            setJob(j);
            if (j.status === 'completed') {
              const p = await api.getJobPlan(targetJobId);
              setPlan(p);
            }
          }
        } catch (e) {
          console.error(e);
        }
      };
      fetchJob();
    }
  }, [episode, jobId]);

  if (isLoading && !data) return <p className="message">Загрузка...</p>;
  if (error || !episode) return <p className="message">Серия не найдена</p>;

  return (
    <main className="screen-shell">
      <div className="screen-toolbar">
        <div>
          <h1 className="page-title">Проверка монтажа {episode.number}</h1>
        </div>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          {episode.jobs && episode.jobs.length > 0 && (
            <select 
              id="episode-attempt" 
              className="form-select"
              value={job?.id || ''}
              onChange={e => {
                const newId = e.target.value;
                if (newId) {
                  navigate(`/episode/${episode.id}/review/${newId}`);
                }
              }}
            >
              <option value="" disabled>Загрузка...</option>
              {/* Note: In legacy UI, it only showed completed jobs. Let's just map all jobs or completed ones. For parity, let's fetch all jobs' statuses.
                  To do this properly, we need a separate state or just list the IDs. We'll list IDs for now, ideally we should show 'Последний монтаж' etc. */}
              {episode.jobs.map((jid, i) => (
                <option key={jid} value={jid}>Монтаж {i + 1} ({jid.substring(0, 8)})</option>
              ))}
            </select>
          )}
          <Link id="review-edit-link" className="btn-secondary" to={`/episode/${episode.id}/edit`}>⚙ Настройки серии</Link>
        </div>
      </div>
      
      <div className="review-workspace" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        {job && plan ? (
          <>
            {/* Timeline Panel */}
            <Timeline job={job} plan={plan} selectedIndex={selectedIndex} onSelectPart={setSelectedIndex} />
            <QualityWarnings plan={plan} />

            {/* Results Panel */}
            <section id="results-panel" className="panel playlist-panel">
              <div className="panel-heading">
                <h2 id="results-heading" className="panel-title">Готовые шортсы ({job.files?.length || 0})</h2>
              </div>
              
              <div className="shorts-viewer-layout">
                <div className="shorts-player-col">
                  <VideoPlayer file={job.files?.[selectedIndex]} />
                  {/* Music Badge could go here */}
                  {plan.parts[selectedIndex]?.music_track && (
                    <div id="music-badge" className="notice" style={{ marginTop: '12px', padding: '8px 12px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                      <span>🎵</span>
                      <div>
                        <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-secondary)' }}>Фоновая музыка</div>
                        <strong id="music-track-name" style={{ fontSize: '13px' }}>{plan.parts[selectedIndex].music_track}</strong>
                      </div>
                    </div>
                  )}
                </div>

                <div className="shorts-playlist-col">
                  <p className="small muted" style={{ marginBottom: '10px', fontWeight: 600 }}>Выберите часть для просмотра:</p>
                  <Playlist files={job.files || []} selectedIndex={selectedIndex} onSelect={setSelectedIndex} />
                  
                  <div style={{ marginTop: '24px' }}>
                    <DownloadControls jobId={job.id} files={job.files || []} selectedIndex={selectedIndex} />
                  </div>

                  <PartContext part={plan.parts[selectedIndex]} />
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
