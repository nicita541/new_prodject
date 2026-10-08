import type { Plan } from '../api/types';

interface QualityWarningsProps {
  plan: Plan | null;
}

export function QualityWarnings({ plan }: QualityWarningsProps) {
  if (!plan) return null;

  const summary = plan.quality_summary;
  const oldWarnings = plan.warnings || [];
  
  // Aggregate warnings
  const warnings = [...oldWarnings.map(w => ({ text: typeof w === 'string' ? w : (w as import('../api/types').QualityWarningItem).text }))];
  if (summary?.warnings) {
    summary.warnings.forEach(w => warnings.push({ text: typeof w === 'string' ? w : w.text }));
  }

  const notes = summary?.notes || [];

  if (warnings.length === 0 && notes.length === 0) return null;

  return (
    <section id="quality-warnings" className="panel quality-panel">
      <div className="panel-heading">
        <h2 id="quality-summary" className="panel-title">
          Оценка качества {warnings.length > 0 ? `· замечаний: ${warnings.length}` : ''}
        </h2>
      </div>
      
      <details>
        <summary className="settings-summary">Посмотреть замечания и примечания</summary>
        <div className="quality-details">
      {warnings.length > 0 && (
        <ul id="quality-warning-list" className="quality-list warnings">
          {warnings.map((w, i) => (
            <li key={i}>{w.text}</li>
          ))}
        </ul>
      )}

      {notes.length > 0 && (
        <div id="quality-notes" style={{ marginTop: '16px' }}>
          <h3 className="muted small" style={{ marginBottom: '8px', fontWeight: 600 }}>Примечания анализа</h3>
          <ul id="quality-note-list" className="quality-list notes">
            {notes.map((n, i) => (
              <li key={i}>{typeof n === 'string' ? n : (n as import('../api/types').QualityWarningItem).text}</li>
            ))}
          </ul>
        </div>
      )}
        </div>
      </details>
    </section>
  );
}
