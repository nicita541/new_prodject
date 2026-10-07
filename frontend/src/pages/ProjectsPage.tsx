import { useState } from 'react';
import { useLibrary } from '../hooks/useLibrary';
import { api } from '../api/client';
import { Link } from 'react-router-dom';

export function ProjectsPage() {
  const { data, isLoading, error, refetch } = useLibrary();
  const [title, setTitle] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  const projects = data?.projects || [];

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || isCreating) return;
    setIsCreating(true);
    try {
      await api.createProject(title.trim());
      setTitle('');
      await refetch();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Ошибка при создании проекта');
    } finally {
      setIsCreating(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await api.deleteProject(id);
      await refetch();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Ошибка при удалении проекта');
    }
  };

  if (isLoading && !data) {
    return <p className="message">Загрузка проектов...</p>;
  }

  if (error) {
    return <p className="message" style={{ color: 'var(--danger)' }}>{error.message}</p>;
  }

  return (
    <main className="screen-shell">
      <nav id="breadcrumbs" className="breadcrumbs" aria-label="Путь проекта">
        {/* Empty breadcrumbs for root */}
      </nav>
      <div className="screen-toolbar">
        <div>
          <h1 id="workspace-title" className="page-title">Проекты аниме</h1>
          <p id="screen-context" className="page-desc">Выберите проект или создайте новый.</p>
        </div>
      </div>
      
      <section id="projects-screen" className="app-screen" aria-label="Проекты">
        <div className="action-bar">
          <form id="project-form" className="action-bar-form" onSubmit={handleCreate}>
            <input 
              type="text" 
              id="project-title" 
              className="form-input" 
              placeholder="Название нового проекта (например: Магическая битва)" 
              required 
              style={{ flex: 1 }}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={isCreating}
            />
            <button type="submit" className="btn-primary" disabled={isCreating}>+ Создать проект</button>
          </form>
        </div>
        
        {projects.length > 0 ? (
          <div id="project-cards" className="grid-cards">
            {projects.map((project, index) => {
              const episodesCount = project.episodes?.length || 0;
              const readyCount = project.episodes?.filter(e => 
                // @ts-ignore - jobs might not be populated cleanly here, or we need to check if there are completed jobs
                e.jobs && e.jobs.some((job: any) => job.status === 'completed')
              ).length || 0;
              const isDeleting = false;
              
              return (
                <div key={project.id} className="item-card-wrap">
                  <Link to={`/project/${project.id}`} className="item-card">
                    <span className={`project-monogram color-${index % 4}`}>
                      {project.title.slice(0, 1).toUpperCase()}
                    </span>
                    <h2 className="card-title">{project.title}</h2>
                    <p className="card-meta">
                      Серий: {episodesCount} · готовы: {readyCount}
                    </p>
                    <span className="btn-text card-actions">Открыть проект</span>
                  </Link>
                  <button 
                    type="button"
                    className="danger-button" 
                    disabled={isDeleting}
                    onClick={(e) => handleDelete(e, project.id)}
                  >
                    Удалить проект
                  </button>
                </div>
              );

            })}
          </div>
        ) : (
          <div id="projects-empty" className="empty-state">Нет проектов. Создайте первый проект выше.</div>
        )}
      </section>
    </main>
  );
}
