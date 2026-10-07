import { useState, useEffect } from 'react';
import { api } from '../api/client';
import type { MusicSettings } from '../api/types';

export function MusicPanel({ partCount = 15 }: { partCount?: number }) {
  const [settings, setSettings] = useState<MusicSettings | null>(null);
  const [msg, setMsg] = useState('');

  const loadSettings = async () => {
    try {
      const data = await api.getMusicSettings();
      setSettings(data);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Ошибка загрузки музыки');
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const handleChange = async (newSettings: Partial<MusicSettings>) => {
    if (!settings) return;
    const updated = { ...settings, ...newSettings };
    setSettings(updated);
    try {
      await api.saveMusicSettings({
        enabled: updated.enabled,
        volume: updated.volume,
        mode: updated.mode,
        track: updated.track,
        part_tracks: updated.part_tracks
      });
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Ошибка сохранения');
    }
  };

  const handleOpenFolder = async () => {
    try {
      const res = await api.openMusicFolder();
      setMsg(`Папка открыта: ${res.path}`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Не удалось открыть папку');
    }
  };

  const handlePartTrackChange = (partIndex: number, track: string) => {
    if (!settings) return;
    const newPartTracks = { ...(settings.part_tracks || {}) };
    const key = String(partIndex + 1); // 1-based indexing for legacy compatibility
    if (track) {
      newPartTracks[key] = track;
    } else {
      delete newPartTracks[key];
    }
    handleChange({ part_tracks: newPartTracks });
  };

  if (!settings) return null;

  return (
    <div className="settings-group">
      <details id="music-section" className="form-group" open>
        <summary className="settings-summary">
          Фоновая музыка <span id="music-summary" className="muted small">
            {settings.enabled ? (settings.mode === 'random_per_part' ? 'случайный для каждого' : settings.mode === 'per_part' ? 'по фрагментам' : (settings.track || 'один трек')) : 'выключена'}
          </span>
        </summary>
        <div className="settings-content">
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13.5px' }}>
            <input type="checkbox" id="music-enabled" checked={settings.enabled} onChange={e => handleChange({ enabled: e.target.checked })} /> Добавлять фоновую музыку
          </label>
          
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginTop: '8px' }}>
            <button id="music-open-folder" type="button" className="btn-secondary" onClick={handleOpenFolder}>Открыть папку</button>
            <button id="music-refresh" type="button" className="btn-secondary" onClick={loadSettings}>↻ Обновить</button>
          </div>

          <div className="form-group" style={{ marginTop: '16px' }}>
            <label id="music-volume-label" className="form-label" htmlFor="music-volume">Громкость ({Math.round(settings.volume * 100)}%)</label>
            <input type="range" id="music-volume" min="0" max="100" step="1" value={settings.volume * 100} style={{ width: '100%' }} onChange={e => handleChange({ volume: Number(e.target.value) / 100 })} disabled={!settings.enabled} />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="music-mode">Режим подстановки</label>
            <select id="music-mode" className="form-select" value={settings.mode} onChange={e => handleChange({ mode: e.target.value as MusicSettings['mode'] })} disabled={!settings.enabled}>
              <option value="single">Один трек на всё видео</option>
              <option value="random_per_part">Случайный трек для каждой части</option>
              <option value="per_part">Выбрать вручную для каждой части</option>
            </select>
          </div>

          {settings.mode === 'single' && (
            <div id="music-single-panel" className="form-group">
              <label className="form-label" htmlFor="music-track">Трек</label>
              <select id="music-track" className="form-select" value={settings.track || ''} onChange={e => handleChange({ track: e.target.value })} disabled={!settings.enabled}>
                <option value="">🎲 Случайный трек</option>
                {settings.tracks?.map(t => (
                  <option key={t} value={t}>🎵 {t}</option>
                ))}
              </select>
            </div>
          )}

          {settings.mode === 'per_part' && (
            <div id="music-parts-panel" className="form-group" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label className="form-label">Музыка для частей</label>
              {Array.from({ length: partCount }).map((_, i) => (
                <div key={i} style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <span style={{ fontSize: '13px', width: '60px' }}>Часть {String(i + 1).padStart(2, '0')}</span>
                  <select 
                    className="form-select" 
                    style={{ flex: 1 }}
                    value={settings.part_tracks?.[String(i + 1)] || ''}
                    onChange={e => handlePartTrackChange(i, e.target.value)}
                    disabled={!settings.enabled}
                  >
                    <option value="">🎲 Случайный трек</option>
                    <option value="none">🔇 Без музыки</option>
                    {settings.tracks?.map(t => (
                      <option key={t} value={t}>🎵 {t}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}

          {msg && <p id="music-message" className="message" role="status">{msg}</p>}
        </div>
      </details>
    </div>
  );
}
