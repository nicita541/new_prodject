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
  const [fetchError, setFetchError] = useState<string>('');
  const [allEpisodeJobs, setAllEpisodeJobs] = useState<Job[]>([]);

  // Load all jobs for the dropdown
  useEffect(() => {
    if (episode && episode.jobs) {
      Promise.all(episode.jobs.map(id => api.getJob(id).catch(() => null)))
        .then(jobs => {
          const validJobs = jobs.filter((j): j is Job => j !== null);
          // Sort or preserve order (usually newest is last in episode.jobs, but let's check completion)
          setAllEpisodeJobs(validJobs);
        });
    }
  }, [episode]);

  useEffect(() => {
    if (!episode || !episode.jobs) return;
    
    const fetchJob = async () => {
      setFetchError('');
      setJob(null);
      setPlan(null);
      setSelectedIndex(0);

      try {
        let targetJobId = jobId;
        
        if (targetJobId && !episode.jobs!.includes(targetJobId)) {
          setFetchError('Монтаж не принадлежит данной серии');
          return;
        }

        if (!targetJobId) {
          // Find latest completed job dynamically
          const allJobs = await Promise.all(episode.jobs!.map(id => api.getJob(id).catch(() => null)));
          const completed = allJobs.filter((j): j is Job => j !== null && j.status === 'completed');
          if (completed.length > 0) {
            // Assume the last one in the array is the latest
            targetJobId = completed[completed.length - 1].id;
          }
        }

        if (targetJobId) {
          const j = await api.getJob(targetJobId);
          setJob(j);
          if (j.status === 'completed') {
            const p = await api.getJobPlan(targetJobId);
            setPlan(p);
          }
        } else {
          setFetchError('Нет завершённых монтажей для проверки');
        }
      } catch (e) {
        setFetchError(e instanceof Error ? e.message : 'Ошибка загрузки данных');
      }
    };
    fetchJob();
  }, [episode, jobId]);

  if (isLoading && !data) return <p className="message">Загрузка...</p>;
  if (error || !episode) return <p className="message">Серия не найдена</p>;

  const filesCount = job?.files?.length || 0;
  const partsCount = plan?.parts?.length || 0;
  const maxIndex = Math.max(0, Math.min(filesCount - 1, partsCount - 1));
  const activeIndex = Math.min(selectedIndex, maxIndex);

  return (
    <main className="screen-shell">
      <div className="screen-toolbar">
        <div>
          <h1 className="page-title">Проверка монтажа {episode.number}</h1>
        </div>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          {allEpisodeJobs.length > 0 && (
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
              {allEpisodeJobs.map((j, i) => (
                <option key={j.id} value={j.id}>
                  Монтаж {i + 1} ({j.id.substring(0, 8)}) {j.status === 'completed' ? '· Готово' : '· Ошибка'}
                </option>
              ))}
            </select>
          )}
          <Link id="review-edit-link" className="btn-secondary" to={`/episode/${episode.id}/edit`}>⚙ Настройки серии</Link>
        </div>
      </div>
      
      <div className="review-workspace" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        {fetchError && <p className="message" style={{ color: 'var(--danger)' }}>{fetchError}</p>}
        {job && plan ? (
          <>
            {/* Timeline Panel */}
            <Timeline job={job} plan={plan} selectedIndex={activeIndex} onSelectPart={setSelectedIndex} />
            <QualityWarnings plan={plan} />

            {/* Results Panel */}
            <section id="results-panel" className="panel playlist-panel">
              <div className="panel-heading">
                <h2 id="results-heading" className="panel-title">Готовые шортсы ({filesCount})</h2>
              </div>
              
              <div className="shorts-viewer-layout">
                <div className="shorts-player-col">
                  <VideoPlayer file={job.files?.[activeIndex]} />
                  {/* Music Badge could go here */}
                  {plan.parts[activeIndex]?.music_track && (
                    <div id="music-badge" className="notice" style={{ marginTop: '12px', padding: '8px 12px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                      <span>🎵</span>
                      <div>
                        <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-secondary)' }}>Фоновая музыка</div>
                        <strong id="music-track-name" style={{ fontSize: '13px' }}>{plan.parts[activeIndex].music_track}</strong>
                      </div>
                    </div>
                  )}
                </div>

                <div className="shorts-playlist-col">
                  <p className="small muted" style={{ marginBottom: '10px', fontWeight: 600 }}>Выберите часть для просмотра:</p>
                  <Playlist files={job.files || []} selectedIndex={activeIndex} onSelect={setSelectedIndex} />
                  
                  <div style={{ marginTop: '24px' }}>
                    <DownloadControls jobId={job.id} files={job.files || []} selectedIndex={activeIndex} />
                  </div>

                  <PartContext part={plan.parts[activeIndex]} />
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
