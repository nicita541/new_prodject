import { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useLibrary } from '../hooks/useLibrary';
import { api } from '../api/client';

export function EpisodesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { data, isLoading, error, refetch } = useLibrary();
  
  const project = data?.projects.find(p => p.id === projectId);
  const episodes = project?.episodes || [];
  
  const [episodeNumber, setEpisodeNumber] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  // Initialize episode number to the next max if not set manually (handled simply here)

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!projectId || isCreating) return;
    setIsCreating(true);
    try {
      const num = parseInt(episodeNumber, 10);
      const ep = await api.createEpisode(projectId, isNaN(num) ? undefined : num);
      setEpisodeNumber('');
      await refetch();
      navigate(`/episode/${ep.id}/edit`);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Ошибка при создании серии');
    } finally {
      setIsCreating(false);
    }
  };

  const handleDeleteProject = async () => {
    if (!projectId || isDeleting) return;
    setIsDeleting(true);
    try {
      await api.deleteProject(projectId);
      await refetch();
      navigate('/projects');
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Ошибка при удалении проекта');
    } finally {
      setIsDeleting(false);
    }
  };

  const handleDeleteEpisode = async (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await api.deleteEpisode(id);
      await refetch();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Ошибка при удалении серии');
    }
  };

  if (isLoading && !data) return <p className="message">Загрузка...</p>;
  if (error) return <p className="message" style={{ color: 'var(--danger)' }}>{error.message}</p>;
  if (!project) return <p className="message">Проект не найден</p>;

  // Recommend next episode number
  const nextNumber = Math.max(0, ...episodes.map(e => e.number)) + 1;

  return (
    <main className="screen-shell">
      <nav id="breadcrumbs" className="breadcrumbs" aria-label="Путь проекта">
        <Link to="/projects">Проекты</Link>
        <Link to={`/project/${project.id}`}>{project.title}</Link>
      </nav>
      <div className="screen-toolbar">
        <div>
          <h1 id="workspace-title" className="page-title">{project.title}</h1>
          <p id="screen-context" className="page-desc">{episodes.length} серий</p>
        </div>
      </div>

      <section id="episodes-screen" className="app-screen" aria-label="Серии">
        <div className="action-bar" style={{ justifyContent: 'space-between' }}>
          <form id="episode-form" style={{ display: 'flex', alignItems: 'center', gap: '12px' }} onSubmit={handleCreate}>
            <span className="muted small" style={{ whiteSpace: 'nowrap', fontWeight: 600 }}>Номер серии:</span>
            <input 
              type="number" 
              id="episode-number" 
              className="form-input" 
              min="1" 
              step="1" 
              required 
              style={{ width: '80px' }}
              value={episodeNumber}
              onChange={e => setEpisodeNumber(e.target.value)}
              placeholder={String(nextNumber)}
            />
            <button type="submit" className="btn-primary" disabled={isCreating}>+ Добавить серию</button>
          </form>
          <button 
            id="delete-current-project" 
            className="btn-danger" 
            type="button" 
            onClick={handleDeleteProject}
            disabled={isDeleting}
          >
            Удалить проект
          </button>
        </div>
        
        {episodes.length > 0 ? (
          <div id="episode-cards" className="grid-cards">
            {episodes.map(episode => {
              const jobs = episode.jobs || [];
              const lastJobId = jobs[jobs.length - 1];
              
              const metaText = jobs.length > 0
                ? `монтажей: ${jobs.length}`
                : episode.source_id ? 'Видео добавлено · монтаж не запускался' : 'Добавьте видео этой серии';

              return (
                <article key={episode.id} className="item-card">
                  <span className="card-icon">{String(episode.number).padStart(2, '0')}</span>
                  <h2 className="card-title">Серия {episode.number}</h2>
                  <p className="card-meta">{metaText}</p>
                  <div className="card-actions">
                    <Link className="btn-secondary" to={`/episode/${episode.id}/edit`}>Настроить монтаж</Link>
                    {jobs.length > 0 && (
                      <Link className="btn-text" to={`/episode/${episode.id}/review/${lastJobId}`}>
                        Посмотреть результаты
                      </Link>
                    )}
                    <button 
                      className="danger-button" 
                      type="button"
                      onClick={(e) => handleDeleteEpisode(e, episode.id)}
                    >
                      Удалить серию
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div id="episodes-empty" className="empty-state">Нет добавленных серий.</div>
        )}
      </section>
    </main>
  );
}
