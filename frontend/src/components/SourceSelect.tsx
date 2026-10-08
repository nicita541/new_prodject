import { useEffect, useRef, useState } from 'react';
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
  const [error, setError] = useState('');
  const uploadingRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchSources = async () => {
    try {
      const data = await api.getSources();
      setSources(data);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить список видео. Обновите список.');
    }
  };

  useEffect(() => {
    fetchSources();
  }, []);

  const uploadFile = (file: File | undefined) => {
    if (!file || disabled || uploadingRef.current) return;
    if (!/\.(mp4|mkv|webm)$/i.test(file.name)) {
      setError('Выберите видео MP4, MKV или WebM.');
      return;
    }
    uploadingRef.current = true;
    setError('');
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
        try {
          const response = JSON.parse(xhr.responseText);
          if (typeof response.id !== 'string' || !response.id) throw new Error('Сервер не вернул загруженный видеофайл.');
          fetchSources().then(() => onChange(response.id));
        } catch {
          setError('Не удалось прочитать ответ загрузки. Обновите список видео.');
        }
      } else {
        setError('Ошибка загрузки: ' + xhr.responseText);
      }
      uploadingRef.current = false;
      setIsUploading(false);
    };

    xhr.onerror = () => {
      setError('Не удалось загрузить видео. Проверьте подключение и повторите загрузку.');
      uploadingRef.current = false;
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
        <div className="upload-zone" id="upload-button" tabIndex={isUploading ? -1 : 0} role="button" aria-label="Загрузить файл" aria-disabled={isUploading}
          onClick={() => !isUploading && fileInputRef.current?.click()}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (!isUploading) fileInputRef.current?.click(); } }}
          onDragOver={e => e.preventDefault()}
          onDrop={e => { e.preventDefault(); uploadFile(e.dataTransfer.files[0]); }}>
          <span className="upload-icon">⇪</span>
          <span className="upload-text" id="upload-label">Перетащите или нажмите для загрузки видео</span>
          <span className="upload-hint">MP4, MKV или WebM</span>
          <input ref={fileInputRef} type="file" id="file-input" accept=".mp4,.mkv,.webm" hidden onClick={e => e.stopPropagation()} onChange={e => { uploadFile(e.target.files?.[0]); e.target.value = ''; }} disabled={isUploading} />
        </div>
      )}
      {error && <p className="message" role="alert">{error}</p>}

      {isUploading && (
        <div id="upload-progress" className="form-group" style={{ marginTop: '14px' }}>
          <progress id="upload-meter" max="100" value={progress}></progress>
        </div>
      )}
    </>
  );
}
