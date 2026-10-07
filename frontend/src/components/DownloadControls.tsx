import { useState } from 'react';
import { api } from '../api/client';
import type { JobFile } from '../api/types';

interface DownloadControlsProps {
  jobId: string;
  files: JobFile[];
  selectedIndex: number;
}

export function DownloadControls({ jobId, files, selectedIndex }: DownloadControlsProps) {
  const [downloadStatus, setDownloadStatus] = useState<string>('');
  const [isDownloading, setIsDownloading] = useState(false);

  const currentFile = files[selectedIndex];

  const handleDownloadAll = async () => {
    if (isDownloading) return;
    setIsDownloading(true);
    setDownloadStatus('Выберите папку для сохранения...');
    try {
      const res = await api.saveVideos(jobId, true);
      if (res.cancelled) {
        setDownloadStatus('Сохранение отменено.');
      } else {
        setDownloadStatus(`Успешно сохранено видео: ${res.count}`);
      }
    } catch (err) {
      setDownloadStatus(`Не удалось сохранить видео: ${err instanceof Error ? err.message : 'Ошибка'}`);
    } finally {
      setIsDownloading(false);
    }
  };

  const handleDownloadSingle = async () => {
    if (!currentFile || isDownloading) return;
    setIsDownloading(true);
    setDownloadStatus('Выберите папку для сохранения...');
    try {
      const res = await api.saveVideos(jobId, false, currentFile.name);
      if (res.cancelled) {
        setDownloadStatus('Сохранение отменено.');
      } else {
        setDownloadStatus('MP4 сохранён в выбранную папку.');
      }
    } catch (err) {
      setDownloadStatus(`Не удалось сохранить: ${err instanceof Error ? err.message : 'Ошибка'}`);
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <div className="shorts-download-actions">
      <div style={{ display: 'flex', gap: '8px' }}>
        <button 
          id="download-video" 
          type="button" 
          className="btn-primary" 
          disabled={!currentFile || isDownloading}
          onClick={handleDownloadSingle}
        >
          Скачать MP4
        </button>
        {currentFile?.subtitle_url && (
          <a 
            id="download-subtitle" 
            className="btn-secondary" 
            href={currentFile.subtitle_url + '?download=1'} 
            download={currentFile.name.replace(/\.mp4$/, '.srt')}
            aria-disabled={!currentFile || isDownloading}
          >
            Субтитры
          </a>
        )}
      </div>
      <button 
        id="download-all" 
        type="button" 
        className="btn-secondary" 
        disabled={files.length === 0 || isDownloading}
        onClick={handleDownloadAll}
        style={{ marginTop: '8px', width: '100%' }}
      >
        Сохранить все ({files.length}) в папку...
      </button>
      {downloadStatus && (
        <p id="download-status" className="muted small" style={{ marginTop: '8px' }}>
          {downloadStatus}
        </p>
      )}
    </div>
  );
}
