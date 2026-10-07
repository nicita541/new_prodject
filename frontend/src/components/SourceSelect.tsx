import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Source } from '../api/types';

interface SourceSelectProps {
  sourceId: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  episodeId: string;
}

export function SourceSelect({ sourceId, onChange, disabled }: SourceSelectProps) {
  const [sources, setSources] = useState<Source[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState(0);

  const fetchSources = async () => {
    try {
      const data = await api.getSources();
      setSources(data);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchSources();
  }, []);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setProgress(0);

    const formData = new FormData();
    formData.append('file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/import', true);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        setProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status === 201) {
        const response = JSON.parse(xhr.responseText);
        fetchSources().then(() => {
          onChange(response.id);
          setIsUploading(false);
        });
      } else {
        alert('Ошибка загрузки: ' + xhr.responseText);
        setIsUploading(false);
      }
    };

    xhr.onerror = () => {
      alert('Network error');
      setIsUploading(false);
    };

    xhr.send(formData);
  };

  return (
    <>
      <div className="form-group">
        <label className="form-label" htmlFor="source">Видеофайл</label>
        <div style={{ display: 'flex', gap: '12px' }}>
          <select 
            id="source" 
            className="form-select" 
            required 
            style={{ flex: 1 }}
            value={sourceId}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled || isUploading}
          >
            <option value="" hidden disabled>Выберите видео этой серии</option>
            {sources.length === 0 && <option value="" disabled>Нет видео. Добавьте MP4 или MKV.</option>}
            {sources.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button id="refresh-sources" type="button" className="btn-secondary" title="Обновить список" onClick={fetchSources} disabled={disabled || isUploading}>↻</button>
        </div>
      </div>

      {!disabled && !sourceId && (
        <div className="upload-zone" id="upload-button" tabIndex={0} role="button" aria-label="Загрузить файл" onClick={() => document.getElementById('file-input')?.click()}>
          <span className="upload-icon">⇪</span>
          <span className="upload-text" id="upload-label">Перетащите или нажмите для загрузки видео</span>
          <span className="upload-hint">MP4, MKV или WebM</span>
          <input type="file" id="file-input" accept="video/mp4,video/x-matroska,video/webm" hidden onChange={handleUpload} disabled={isUploading} />
        </div>
      )}

      {isUploading && (
        <div id="upload-progress" className="form-group" style={{ marginTop: '14px' }}>
          <progress id="upload-meter" max="100" value={progress}></progress>
        </div>
      )}
    </>
  );
}
