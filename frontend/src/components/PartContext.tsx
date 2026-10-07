import { useState } from 'react';
import type { PlanPart } from '../api/types';

interface PartContextProps {
  part: PlanPart | undefined;
}

export function PartContext({ part }: PartContextProps) {
  const [copyStatus, setCopyStatus] = useState('');

  if (!part) return null;

  const context = part.cover_context;
  const isFallback = context?.method === 'extractive' || !context?.prompt;

  const handleCopy = async () => {
    if (!context?.prompt) return;
    const text = `Контекст: ${context.synopsis}\n\n${context.prompt}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus('Скопировано');
      setTimeout(() => setCopyStatus(''), 2000);
    } catch {
      setCopyStatus('Не удалось скопировать');
    }
  };

  return (
    <div id="part-context" className="part-context-block" style={{ marginTop: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 id="part-context-heading" className="panel-title" style={{ fontSize: '13px' }}>
          Заставка · часть {String(part.index || 1).padStart(2, '0')}
        </h3>
        <button 
          id="copy-context" 
          type="button" 
          className="btn-text" 
          style={{ padding: '2px 6px', fontSize: '12px' }}
          onClick={handleCopy}
          disabled={!context?.prompt}
        >
          {copyStatus || 'Скопировать'}
        </button>
      </div>
      <p id="part-context-synopsis" className="muted small" style={{ marginTop: '4px' }}>
        {context?.synopsis || 'Контекст неизвестен'}
      </p>
      {context?.prompt ? (
        <textarea 
          id="part-context-prompt" 
          className="form-input" 
          readOnly 
          style={{ marginTop: '8px', height: '60px', fontSize: '12.5px', resize: 'none' }}
          value={context.prompt}
        />
      ) : null}
      <p id="part-context-fallback" className="notice warning" style={{ marginTop: '8px' }} hidden={!isFallback}>
        DeepSeek не составил описание. Это примерный промпт.
      </p>
      <span id="context-copy-status" className="visually-hidden" role="status">{copyStatus}</span>
    </div>
  );
}
