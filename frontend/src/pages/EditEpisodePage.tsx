import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useLibrary } from '../hooks/useLibrary';
import { api } from '../api/client';
import { JobProgressPanel } from '../components/JobProgressPanel';
import { SourceSelect } from '../components/SourceSelect';
import { DeepSeekPanel } from '../components/DeepSeekPanel';
import { MusicPanel } from '../components/MusicPanel';

export function EditEpisodePage() {
  const { episodeId } = useParams<{ episodeId: string }>();
  const { data, isLoading, error, refetch } = useLibrary();

  // Find project and episode
  const project = data?.projects.find(p => p.episodes.some(e => e.id === episodeId));
  const episode = project?.episodes.find(e => e.id === episodeId);

  // Settings states
  const [sourceId, setSourceId] = useState<string>('');
  const [layout, setLayout] = useState<'portrait' | 'cinema'>('cinema');
  const [captionStyle, setCaptionStyle] = useState<'classic' | 'accent'>('accent');
  const [provider, setProvider] = useState<'local' | 'deepseek' | 'hybrid' | 'deepseek_plan'>('deepseek_plan');

  // Job state
  const [isStarting, setIsStarting] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  
  useEffect(() => {
    if (episode && episode.settings) {
      setSourceId(episode.source_id || '');
      setLayout(episode.settings.layout || 'cinema');
      setCaptionStyle(episode.settings.caption_style || 'accent');
      setProvider(episode.settings.analysis_provider || 'deepseek_plan');
    }
  }, [episode]);

  const handleSaveSettingsOnly = async (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (!episodeId || !sourceId) return;
    try {
      await api.saveEpisodeSettings(episodeId, {
        source_id: sourceId,
        layout,
        caption_style: captionStyle,
        analysis_provider: provider
      });
      setSaveMessage('Настройки этой серии сохранены. Монтаж не запускался.');
      setTimeout(() => setSaveMessage(''), 3000);
    } catch (err) {
      setSaveMessage(err instanceof Error ? err.message : 'Ошибка сохранения');
    }
  };

  const handleSaveAndLaunch = async () => {
    if (!episodeId) return;
    setIsStarting(true);
    try {
      await api.saveEpisodeSettings(episodeId, {
        source_id: sourceId,
        layout,
        caption_style: captionStyle,
        analysis_provider: provider
      });
      await api.launchEpisodeJob(episodeId);
      await refetch();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Ошибка при запуске монтажа');
    } finally {
      setIsStarting(false);
    }
  };

  const handleDeleteEpisode = async () => {
    if (!episodeId) return;
    if (!confirm('Точно удалить серию?')) return;
    try {
      await api.deleteEpisode(episodeId);
      window.location.href = `/project/${project?.id}`;
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Ошибка при удалении');
    }
  };

  if (isLoading && !data) return <p className="message">Загрузка...</p>;
  if (error || !episode) return <p className="message">Серия не найдена</p>;

  // Get current active job
  const activeJobId = episode.jobs?.[0]; // Or fetch full job lists if populated properly

  return (
    <main className="screen-shell">
      <nav id="breadcrumbs" className="breadcrumbs" aria-label="Путь проекта">
        <Link to="/projects">Проекты</Link>
        {project && <Link to={`/project/${project.id}`}>{project.title}</Link>}
        <Link to={`/episode/${episode.id}/edit`}>Серия {episode.number}</Link>
      </nav>
      
      <div className="screen-toolbar">
        <div>
          <h1 id="workspace-title" className="page-title">Серия {episode.number} · настройки монтажа</h1>
          <p id="screen-context" className="page-desc">{project?.title}</p>
        </div>
      </div>

      <section id="edit-screen" className="app-screen" aria-label="Настройки серии">
        <div className="editor-layout">
          
          <div className="panel source-panel">
            <div className="panel-heading">
              <h2 id="source-heading" className="panel-title">Исходник и параметры</h2>
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                <button id="delete-current-episode" className="btn-danger" type="button" onClick={handleDeleteEpisode}>Удалить серию</button>
              </div>
            </div>
            
            <form id="create-form" onSubmit={(e) => { e.preventDefault(); handleSaveAndLaunch(); }}>
              <SourceSelect sourceId={sourceId} onChange={setSourceId} disabled={isStarting || !!episode.source_id} episodeId={episode.id} />
              
              <div className="settings-group">
                <div className="form-group">
                  <label className="form-label" htmlFor="layout">Оформление кадра (9:16 Shorts)</label>
                  <select id="layout" className="form-select" value={layout} onChange={e => setLayout(e.target.value as any)} disabled={isStarting}>
                    <option value="cinema">Весь кадр + мягкий фон (9:16)</option>
                    <option value="portrait">Крупный план · умное кадрирование (9:16)</option>
                  </select>
                </div>

                <div className="style-preview-container">
                  <div style={{ flex: 1 }}>
                    <label className="form-label" htmlFor="caption-style">Субтитры</label>
                    <select id="caption-style" className="form-select" style={{ width: '100%' }} value={captionStyle} onChange={e => setCaptionStyle(e.target.value as any)} disabled={isStarting}>
                      <option value="accent">Яркие · короткие фразы (Жёлтый)</option>
                      <option value="classic">Спокойные · белый текст (Классика)</option>
                    </select>
                  </div>
                  <div id="style-preview" className={`style-preview ${layout} ${captionStyle}`} aria-label="Схема оформления">
                    <span className="preview-part">ЧАСТЬ 01</span>
                    <div className="preview-scene"><span>ВИДЕО</span></div>
                    <strong id="preview-subtitle">
                      {captionStyle === 'accent' ? <>ИСТОРИЯ<br/>НАЧИНАЕТСЯ ЗДЕСЬ</> : <>История<br/>начинается здесь</>}
                    </strong>
                    <span className="preview-hint">9:16 Shorts</span>
                  </div>
                </div>
              </div>

              <div className="settings-group">
                <div className="form-group">
                  <label className="form-label" htmlFor="analysis-provider">Сценарист (Нейросеть)</label>
                  <select id="analysis-provider" className="form-select" value={provider} onChange={e => setProvider(e.target.value as any)} disabled={isStarting}>
                    <option value="deepseek_plan">DeepSeek · сюжет и план (Облако)</option>
                    <option value="hybrid">Локально + DeepSeek API (Старый)</option>
                    <option value="local">На компьютере · без сети (Быстрая)</option>
                  </select>
                </div>
                <p className="muted small" style={{ marginTop: '8px' }}>
                  {provider === 'deepseek_plan' ? 'Анализ видео выполняется с помощью DeepSeek.' : 'Анализ выполняется на компьютере.'}
                </p>
                <DeepSeekPanel />
              </div>

              <MusicPanel />

              <div className="settings-group">
                <p id="form-message" className="message" role="status" hidden={!saveMessage}>{saveMessage}</p>
                <div style={{ display: 'flex', gap: '16px', alignItems: 'center', justifyContent: 'space-between' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
                    <input 
                      type="checkbox" 
                      id="save-settings" 
                      onChange={handleSaveSettingsOnly} 
                      disabled={isStarting || !sourceId} 
                      checked={false} // Always uncontrolled/stateless, acts as a button
                    /> 
                    Сохранить по умолчанию
                  </label>
                  <button id="create-button" type="submit" className="btn-primary" disabled={isStarting || !sourceId}>
                    {isStarting ? 'Запускаем...' : 'Смонтировать'}
                  </button>
                </div>
              </div>

            </form>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <JobProgressPanel jobId={typeof activeJobId === 'string' ? activeJobId : ((activeJobId as any)?.id || null)} episodeId={episode.id} />
          </div>
        </div>
      </section>
    </main>
  );
}
