import { useLibrary } from '../hooks/useLibrary';
import { api } from '../api/client';
import { Link } from 'react-router-dom';
import { archivedProjects, archivedEpisodes, projectById } from '../library/selectors';

export function TrashPage() {
  const { data, isLoading, error, refetch } = useLibrary();

  const handleRestoreProject = async (id: string) => {
    try {
      await api.restoreProject(id);
      await refetch();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Ошибка восстановления');
    }
  };

  const handleRestoreEpisode = async (id: string) => {
    try {
      await api.restoreEpisode(id);
      await refetch();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Ошибка восстановления');
    }
  };

  if (isLoading && !data) return <p className="message">Загрузка...</p>;
  if (error) return <p className="message" style={{ color: 'var(--danger)' }}>{error.message}</p>;

  const trashProjects = archivedProjects(data);
  const trashEpisodes = archivedEpisodes(data);
  const hasItems = trashProjects.length > 0 || trashEpisodes.length > 0;

  return (
    <main className="screen-shell">
      <nav id="breadcrumbs" className="breadcrumbs" aria-label="Путь проекта">
        <Link to="/projects">Проекты</Link>
        <Link to="/trash">Корзина</Link>
      </nav>
      <div className="screen-toolbar">
        <div>
          <h1 id="workspace-title" className="page-title">Корзина</h1>
          <p id="screen-context" className="page-desc">Можно восстановить</p>
        </div>
      </div>
      
      <section id="trash-screen" className="app-screen" aria-label="Корзина">
        {hasItems ? (
          <div id="trash-cards" className="grid-cards">
            {trashProjects.map((project) => (
              <article key={`p-${project.id}`} className="item-card">
                <h2 className="card-title">{project.title}</h2>
                <p className="card-meta">Проект · вместе со всеми сериями</p>
                <button type="button" className="secondary-button" onClick={() => handleRestoreProject(project.id)}>
                  Восстановить проект
                </button>
              </article>
            ))}
            {trashEpisodes.map(episode => (
              <article key={`e-${episode.id}`} className="item-card">
                <h2 className="card-title">Серия {episode.number}</h2>
                <p className="card-meta">{projectById(data, episode.project_id)?.title}</p>
                <button type="button" className="secondary-button" onClick={() => handleRestoreEpisode(episode.id)}>
                  Восстановить серию
                </button>
              </article>
            ))}
          </div>
        ) : (
          <div id="trash-empty" className="empty-state">Корзина пуста.</div>
        )}
      </section>
    </main>
  );
}
