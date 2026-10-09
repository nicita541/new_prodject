import { useJobPolling } from '../hooks/useJobPolling';
import { api } from '../api/client';
import { Link } from 'react-router-dom';

const statuses: Record<string, string> = {
  queued: "В очереди", running: "В работе", completed: "Готово", failed: "Ошибка", cancelled: "Отменено", interrupted: "Прервано"
};

const providers: Record<string, string> = {
  local: 'На компьютере', deepseek: 'DeepSeek', deepseek_plan: 'DeepSeek',
  hybrid: 'На компьютере и DeepSeek'
};

const stages: Record<string, string> = {
  global_verify: "Проверка изображения и сюжета", quality_gate: "Проверка качества монтажа",
  queued: "Ожидание", prepare: "Подготовка видео", preparing: "Подготовка видео", probe: "Проверка видео", audio: "Подготовка звука", transcribe: "Распознавание русской речи", transcribing: "Распознавание русской речи", transcript: "Распознавание русской речи", speech: "Распознавание русской речи", scenes: "Поиск смысловых сцен", shots: "Поиск смены планов", analyze: "Анализ сюжета и изображения", analyzing: "Анализ сюжета и изображения", analysis: "Анализ сюжета и изображения", events: "Анализ сюжета и изображения", condense: "Сокращение сюжета с сохранением контекста", framing: "Кадрирование говорящих и действия", focus: "Кадрирование говорящих и действия", plan: "Составление монтажного плана", planning: "Составление монтажного плана", render: "Экспорт частей", rendering: "Экспорт частей", completed: "Монтаж завершён", done: "Монтаж завершён"
};

const checkpointStages = ["prepare", "transcribe", "scenes", "analyze", "condense", "framing", "plan", "render"] as const;

const stepStatuses = {
  pending: { stateName: 'pending', label: 'Ожидает' },
  running: { stateName: 'current', label: 'Выполняется' },
  completed: { stateName: 'done', label: 'Готово' },
  failed: { stateName: 'failed', label: 'Остановлено с ошибкой' },
  cancelled: { stateName: 'cancelled', label: 'Отменено' },
  interrupted: { stateName: 'interrupted', label: 'Прервано' }
};

const stageGroup: Record<string, number> = {
  queued: 0,
  scenes: 2, shots: 2, global_verify: 3, quality_gate: 6,
  prepare: 0, preparing: 0, probe: 0, audio: 0, transcribe: 1, transcribing: 1, transcript: 1, speech: 1, analyze: 3, analyzing: 3, analysis: 3, events: 3, condense: 4, framing: 5, focus: 5, planning: 6, plan: 6, rendering: 7, render: 7, completed: 8, done: 8
};

export function JobProgressPanel({ jobId, episodeId }: { jobId: string | null, episodeId: string }) {
  const { job, refresh } = useJobPolling(jobId);

  if (!job) {
    return (
      <div className="panel history-panel">
        <div className="panel-heading">
          <h2 className="panel-title">Монтаж пока не запускался</h2>
        </div>
      </div>
    );
  }

  const group = stageGroup[job.stage];
  const recognized = Number.isInteger(group);
  const active = job.status === "running" && job.stage !== 'queued' && recognized && group < checkpointStages.length;

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

      {providers[job.analysis_provider] && (
        <p id="job-provider" className="muted small">Этот запуск: {providers[job.analysis_provider]}</p>
      )}
      
      <div>
        <div style={{ fontSize: '12px', marginBottom: '8px' }}>
          <span id="stage-label" style={{ fontWeight: 600 }}>{stages[job.stage] || job.stage}</span>
        </div>
        {job.message && <p id="job-message" className={job.status === 'failed' ? 'message' : 'notice'} role="status">{job.message}</p>}
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

          const serverStep = job.stage_progress?.[step];
          if (serverStep) ({ stateName, label } = stepStatuses[serverStep.status]);
          const serverFraction = serverStep?.fraction;
          const fraction = typeof serverFraction === 'number' && Number.isFinite(serverFraction)
            ? Math.max(0, Math.min(1, serverFraction))
            : stateName === 'done' ? 1 : stateName === 'pending' ? 0 : undefined;
          const percent = fraction === undefined ? undefined : fraction * 100;
          const percentLabel = percent === undefined ? undefined : percent > 0 && percent < 1
            ? percent.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
            : String(Math.round(percent));
          const hasCounts = serverStep?.completed !== undefined && serverStep?.total !== undefined;

          return (
            <li key={step} className={`stage-item ${stateName}`} data-stage={step} aria-current={stateName === 'current' ? 'step' : undefined}>
              <div className="stage-icon" aria-hidden="true"></div>
              <div className="stage-copy">
                <div className="stage-heading">
                  <strong>{stages[step]}</strong>
                  {percentLabel !== undefined && <span className="stage-percent">{percentLabel}%</span>}
                </div>
                <progress className="stage-progress" aria-label={`${stages[step]}: ${label}`} aria-valuetext={fraction === undefined ? label : undefined} max="1" value={fraction}></progress>
                <div className="small muted" data-stage-state>{label}</div>
                {serverStep?.phase && <div className="small muted stage-detail">{stages[serverStep.phase] || serverStep.phase}</div>}
                {hasCounts && <div className="small muted stage-detail">{serverStep?.completed} из {serverStep?.total}</div>}
                {serverStep?.detail && <div className="small muted stage-detail">{serverStep.detail}</div>}
              </div>
            </li>
          );
        })}
      </ul>

      <div className="action-row" style={{ marginTop: '24px' }}>
        {['queued', 'running'].includes(job.status) && (
          <button id="cancel-button" type="button" className="btn-danger" onClick={handleCancel} disabled={job.cancel_requested}>
            {job.cancel_requested ? 'Отмена запрошена...' : 'Отменить'}
          </button>
        )}
        {['failed', 'cancelled', 'interrupted'].includes(job.status) && (
          <button id="retry-button" type="button" className="btn-primary" onClick={async () => {
            try { await api.retryJob(job.id); refresh(); } catch { alert('Ошибка повтора'); }
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
