import type { JobFile } from '../api/types';

interface PlaylistProps {
  files: JobFile[];
  selectedIndex: number;
  onSelect: (index: number) => void;
}

export function Playlist({ files, selectedIndex, onSelect }: PlaylistProps) {
  if (files.length === 0) {
    return <p className="muted small">Готовых частей пока нет</p>;
  }

  return (
    <ul id="playlist" className="playlist-list">
      {files.map((file, i) => (
        <li key={i}>
          <button 
            type="button" 
            aria-pressed={i === selectedIndex}
            onClick={() => onSelect(i)}
          >
            <span>Часть {String(i + 1).padStart(2, '0')}</span>
            <span>{file.duration ? file.duration.toFixed(1) + 's' : ''}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
