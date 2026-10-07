import { useJobPolling } from '../hooks/useJobPolling';
import { api } from '../api/client';
import { Link } from 'react-router-dom';

const statuses: Record<string, string> = {
  queued: "В очереди", running: "В работе", completed: "Готово", failed: "Ошибка", cancelled: "Отменено", interrupted: "Прервано"
};

const stages: Record<string, string> = {
  queued: "Ожидание", prepare: "Подготовка видео", preparing: "Подготовка видео", probe: "Проверка видео", audio: "Подготовка звука", transcribe: "Распознавание русской речи", transcribing: "Распознавание русской речи", transcript: "Распознавание русской речи", speech: "Распознавание русской речи", shots: "Поиск смены планов", analyze: "Анализ сюжета и изображения", analyzing: "Анализ сюжета и изображения", analysis: "Анализ сюжета и изображения", events: "Анализ сюжета и изображения", condense: "Сокращение сюжета с сохранением контекста", framing: "Кадрирование говорящих и действия", focus: "Кадрирование говорящих и действия", plan: "Составление монтажного плана", planning: "Составление монтажного плана", render: "Экспорт частей", rendering: "Экспорт частей", completed: "Монтаж завершён", done: "Монтаж завершён"
};

const checkpointStages = ["prepare", "transcribe", "analyze", "condense", "framing", "plan", "render"];

const stageGroup: Record<string, number> = {
  prepare: 0, preparing: 0, probe: 0, audio: 0, transcribe: 1, transcribing: 1, transcript: 1, speech: 1, scenes: 0, shots: 0, analyze: 2, analyzing: 2, analysis: 2, events: 2, condense: 3, framing: 4, focus: 4, planning: 5, plan: 5, rendering: 6, render: 6, completed: 7, done: 7
};

export function JobProgressPanel({ jobId, episodeId }: { jobId: string | null, episodeId: string }) {
  const { job } = useJobPolling(jobId);

  if (!job) {
    return (
      <div className="panel history-panel">
        <div className="panel-heading">
          <h2 className="panel-title">Монтаж пока не запускался</h2>
        </div>
      </div>
    );
  }

  const progress = Math.max(0, Math.min(1, Number(job.progress) || 0));
  const group = stageGroup[job.stage];
  const recognized = Number.isInteger(group);
  const active = job.status === "running" && recognized && group < checkpointStages.length;

  const handleCancel = async () => {
    try {
      await api.cancelJob(job.id);
    } catch {
      alert('Ошибка отмены');
    }
  };

  return (
    <div id="job-panel" className={`panel ${job.status === 'completed' ? 'job-completed' : ''}`}>
      <div className="panel-heading">
        <h2 id="job-heading" className="panel-title">{job.status === 'completed' ? 'Монтаж завершён' : 'Обработка серии'}</h2>
        <span id="job-status" className="badge">{statuses[job.status] || job.status}</span>
      </div>
      
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '8px' }}>
          <span id="stage-label" style={{ fontWeight: 600 }}>{stages[job.stage] || job.stage}</span>
          <span id="progress-label" className="muted">{Math.round(progress * 100)}%</span>
        </div>
        <progress id="job-progress" max="1" value={progress}></progress>
        {job.message && <p id="job-message" className="message" role="status">{job.message}</p>}
        {job.error && <pre id="job-error" className="message" style={{ color: 'var(--danger)', whiteSpace: 'pre-wrap' }}>{job.error}</pre>}
      </div>
      
      <ul className="stages-list">
        {checkpointStages.map((step, index) => {
          let stateName = "pending", label = "Ожидает";
          if (job.status === "completed") { stateName = "done"; label = "Завершено"; }
          else if (active && index === group) { stateName = "current"; label = "Выполняется"; }
          else if (job.status !== "queued" && recognized && group < checkpointStages.length && index < group) { stateName = "done"; label = "Готово"; }
          else if (["failed", "cancelled", "interrupted"].includes(job.status) && recognized && index === group && group < checkpointStages.length) {
            stateName = job.status === "failed" ? "failed" : job.status === "cancelled" ? "cancelled" : "interrupted";
            label = job.status === "failed" ? "Остановлено с ошибкой" : job.status === "cancelled" ? "Отменено" : "Прервано";
          } else if (!recognized && ["running", "failed", "cancelled", "interrupted"].includes(job.status)) { stateName = "unknown"; label = "Стадия сервера не распознана"; }

          return (
            <li key={step} className={`stage-item ${stateName}`} data-stage={step} aria-current={active && index === group ? 'step' : undefined}>
              <div className="stage-icon"></div>
              <div className="stage-copy">
                <strong>{stages[step]}</strong>
                <div className="small muted" data-stage-state>{label}</div>
              </div>
            </li>
          );
        })}
      </ul>

      <div style={{ display: 'flex', gap: '12px', marginTop: '24px' }}>
        {['queued', 'running'].includes(job.status) && (
          <button id="cancel-button" type="button" className="btn-danger" onClick={handleCancel} disabled={job.cancel_requested}>
            {job.cancel_requested ? 'Отмена запрошена...' : 'Отменить'}
          </button>
        )}
        {['failed', 'cancelled', 'interrupted'].includes(job.status) && (
          <button id="retry-button" type="button" className="btn-primary" onClick={async () => {
            try { await api.retryJob(job.id); } catch { alert('Ошибка повтора'); }
          }}>
            Повторить
          </button>
        )}
        {['failed', 'cancelled', 'interrupted'].includes(job.status) && job.error?.includes('budget') && (
          <button id="reset-budget-button" type="button" className="btn-secondary" onClick={async () => {
            try { await api.resetJobBudget(job.id); alert('Лимит сброшен, можно повторить запуск.'); } catch { alert('Ошибка'); }
          }}>
            Сбросить лимит
          </button>
        )}
        {job.status === 'completed' && (
          <Link to={`/episode/${episodeId}/review/${job.id}`} className="btn-primary">
            Проверить результат
          </Link>
        )}
      </div>
    </div>
  );
}
