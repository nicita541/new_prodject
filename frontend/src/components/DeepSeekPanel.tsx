import { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { DeepSeekCheck } from '../api/types';

export function DeepSeekPanel() {
  const [status, setStatus] = useState<DeepSeekCheck | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchStatus = async () => {
    setIsLoading(true);
    try {
      const data = await api.checkDeepSeek();
      setStatus(data);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка подключения');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  return (
    <details id="deepseek-details" className="form-group">
      <summary className="settings-summary">Настройки DeepSeek <span className="muted small" id="provider-balance-time"></span></summary>
      <div className="settings-content">
        {error && (
          <div id="deepseek-check" className="notice" style={{ marginTop: '16px' }}>
            <strong>Проблема с DeepSeek</strong>
            <p id="deepseek-check-message">{error}</p>
          </div>
        )}
        
        {status && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div>
              <label className="form-label">Статус</label>
              <div id="deepseek-budget" style={{ fontSize: '18px', fontWeight: 700, color: status.available ? 'var(--accent-light)' : 'var(--danger)' }}>
                {status.available ? 'Доступен' : 'Недоступен'}
              </div>
            </div>
            <div>
              <label className="form-label">Баланс</label>
              <div id="deepseek-remaining" style={{ fontSize: '18px', fontWeight: 700 }}>
                {status.balance_infos?.map((b, i) => (
                  <span key={i}>{b.total_balance} {b.currency}</span>
                )) || 'Неизвестно'}
              </div>
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <label className="form-label">Модель</label>
              <div id="deepseek-charged" style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>
                {status.model}
              </div>
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: '12px', marginTop: '16px' }}>
          <a href="/docs/ai/deepseek-setup.md" className="btn-text">Инструкция по ключам</a>
          <button id="balance-refresh-button" type="button" className="btn-secondary" onClick={fetchStatus} disabled={isLoading}>
            {isLoading ? 'Обновление...' : 'Обновить баланс'}
          </button>
        </div>
      </div>
    </details>
  );
}
