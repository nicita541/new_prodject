import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useLibrary } from '../hooks/useLibrary';
import { api } from '../api/client';
import type { Job, Plan } from '../api/types';
import { episodeById, projectById, completedJobsForEpisode } from '../library/selectors';
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
  
  const episode = episodeById(data, episodeId);
  const project = projectById(data, episode?.project_id);

  const [job, setJob] = useState<Job | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [viewMode, setViewMode] = useState<'compare' | 'shorts' | 'source'>('compare');
  const [fetchError, setFetchError] = useState<string>('');
  const [isFetching, setIsFetching] = useState(true);
  const allEpisodeJobs = completedJobsForEpisode(episode);

  useEffect(() => {
    let live = true;
    
    const fetchJob = async () => {
      setFetchError('');
      setIsFetching(true);
      setJob(null);
      setPlan(null);
      setSelectedIndex(0); // Reset selectedIndex on job switch

      try {
        if (!episode || episode.archived_at || !project || project.archived_at) return;
        const completed = completedJobsForEpisode(episode);
        let targetJobId = jobId;
        if (targetJobId && !episode.jobs.some(ref => ref.id === targetJobId)) {
          setFetchError('Монтаж не принадлежит данной серии');
          return;
        }

        if (targetJobId && !completed.some(ref => ref.id === targetJobId)) {
          setFetchError('Монтаж ещё не завершён');
          return;
        }
        targetJobId ??= completed[0]?.id;

        if (targetJobId) {
          const j = await api.getJob(targetJobId);
          if (!live) return;
          setJob(j);
          if (j.status === 'completed') {
            const p = await api.getJobPlan(targetJobId);
            if (live) setPlan(p);
          } else {
            setFetchError('Монтаж ещё не завершён');
          }
        } else {
          setFetchError('Нет завершённых монтажей для проверки');
        }
      } catch (e) {
        if (live) setFetchError(e instanceof Error ? e.message : 'Ошибка загрузки данных');
      } finally {
        if (live) setIsFetching(false);
      }
    };
    fetchJob();
    return () => { live = false; };
  }, [episode, project, jobId]);

  if (isLoading && !data) return <p className="message">Загрузка...</p>;
  if (error || !episode || episode.archived_at || !project || project.archived_at) return <p className="message">Серия не найдена</p>;

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
        <div className="toolbar-actions">
          {allEpisodeJobs.length > 0 && (
            <select 
              id="episode-attempt" 
              aria-label="Версия монтажа"
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
                  {i === 0 ? 'Последний монтаж' : 'Предыдущий монтаж'} ({new Date(j.created_at).toLocaleString()})
                </option>
              ))}
            </select>
          )}
          <Link id="review-edit-link" className="btn-secondary" to={`/episode/${episode.id}/edit`}>⚙ Настройки серии</Link>
          {job?.status === 'completed' && <Link className="btn-primary" to={'/episode/' + episode.id + '/finishing/' + job.id}>✦ Оформление</Link>}
        </div>
      </div>
      
      <div className="review-workspace" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        {fetchError && <p className="message" style={{ color: 'var(--danger)' }}>{fetchError}</p>}
        {job && plan ? (
          <>
            <div className="st-review-grid">
              <div className="st-review-main">
                <section id="results-panel" className="st-review-player-panel" aria-label="Проверка видео">
                  <div className="st-review-panel-head">
                    <span>● Исходник + готовый Shorts</span>
                    <div className="st-review-tabs" role="group" aria-label="Режим просмотра">
                      <button type="button" className={viewMode === 'shorts' ? 'active' : ''}
                        onClick={() => setViewMode('shorts')}>Shorts</button>
                      <button type="button" className={viewMode === 'source' ? 'active' : ''}
                        onClick={() => setViewMode('source')}>Исходник</button>
                      <button type="button" className={viewMode === 'compare' ? 'active' : ''}
                        onClick={() => setViewMode('compare')}>Сравнить</button>
                    </div>
                  </div>
                  <div className={'st-review-stage view-' + viewMode}>
                    {viewMode !== 'shorts' && <div className="st-review-original">
                      <small>● Исходная серия · 16:9</small>
                      <video controls playsInline preload="metadata" aria-label="Исходная серия"
                        src={'/api/jobs/' + job.id + '/source'}/>
                    </div>}
                    {viewMode !== 'source' && <div className="st-review-short">
                      <small>● Готовый Shorts · 9:16</small>
                      <VideoPlayer file={job.files?.[activeIndex]}
                        onEnded={activeIndex < filesCount - 1
                          ? () => setSelectedIndex(activeIndex + 1) : undefined}/>
                    </div>}
                  </div>
                  <div className="st-review-player-foot">
                    <span>Часть {activeIndex + 1} из {filesCount} · {plan.parts[activeIndex]?.duration?.toFixed(1) ?? '—'} с</span>
                    <div className="st-review-controls">
                      <button type="button" aria-label="Предыдущий Shorts"
                        disabled={activeIndex === 0} onClick={() => setSelectedIndex(i => Math.max(0,i-1))}>◀</button>
                      <Link to={'/episode/' + episode.id + '/finishing/' + job.id}>✎ Оформление</Link>
                      <button type="button" aria-label="Следующий Shorts"
                        disabled={activeIndex >= maxIndex} onClick={() => setSelectedIndex(i => Math.min(maxIndex,i+1))}>▶</button>
                    </div>
                  </div>
                </section>
                <div className="st-review-timeline" aria-label="Монтажная лента">
                  <Timeline key={job.id} job={job} plan={plan} selectedIndex={activeIndex} onSelectPart={setSelectedIndex}/>
                </div>
                <QualityWarnings plan={plan}/>
              </div>
              <aside className="st-review-rail" aria-label="Готовые Shorts">
                <div className="st-panel-kicker">ГОТОВЫЕ SHORTS</div>
                <h2 id="results-heading">Готовые Shorts ({filesCount})</h2>
                <Playlist files={job.files || []} selectedIndex={activeIndex} onSelect={setSelectedIndex}/>
                {plan.parts[activeIndex]?.music_track && <div id="music-badge" className="st-review-music">
                  ♫ {plan.parts[activeIndex].music_track}
                </div>}
                <div className="st-review-downloads">
                  <div className="st-panel-kicker">СКАЧИВАНИЕ</div>
                  <DownloadControls jobId={job.id} files={job.files || []} selectedIndex={activeIndex}/>
                </div>
                <PartContext part={plan.parts[activeIndex]}/>
              </aside>
            </div>
          </>
        ) : isFetching ? (
          <p className="notice" role="status">Загрузка монтажа...</p>
        ) : !fetchError ? (
          <p id="review-empty" className="empty-state">Готового монтажа пока нет. Вернитесь в настройки серии.</p>
        ) : null}
      </div>
    </main>
  );
}
