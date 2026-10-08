import { useState, useRef, useEffect, useMemo } from 'react';
import type { Plan, Job } from '../api/types';
import { buildTimelinePieces, buildDebugPieces, pieceLabel, sourceTime, DEBUG_KIND_LABELS } from '../utils/timeline';

interface TimelineProps {
  job: Job | null;
  plan: Plan | null;
  selectedIndex: number;
  onSelectPart: (index: number) => void;
}

export function Timeline({ job, plan, selectedIndex, onSelectPart }: TimelineProps) {
  const [zoom, setZoom] = useState(1);
  const [showDebug, setShowDebug] = useState(false);
  const [limitToPart, setLimitToPart] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [sourceSelection, setSourceSelection] = useState<{start: number, end: number, retained: boolean} | null>(null);
  const [activeDebugInfo, setActiveDebugInfo] = useState<{title: string, detail?: string, kind: string, start: number, end: number} | null>(null);
  const [playerError, setPlayerError] = useState(false);
  
  const videoRef = useRef<HTMLVideoElement>(null);
  const timelineMapRef = useRef<HTMLDivElement>(null);

  const duration = plan?.source?.duration || 1;
  const parts = plan?.parts || [];

  const pieces = useMemo(() => plan ? buildTimelinePieces(plan, duration) : [], [plan, duration]);
  const debugPieces = useMemo(() => plan && plan.debug_timeline?.reasons ? buildDebugPieces(plan.debug_timeline.reasons, pieces, duration) : [], [plan, pieces, duration]);

  // Sync player limits and time
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      if (limitToPart && sourceSelection) {
        if (video.currentTime >= sourceSelection.end) {
          video.pause();
        }
      }
    };

    video.addEventListener('timeupdate', handleTimeUpdate);
    return () => video.removeEventListener('timeupdate', handleTimeUpdate);
  }, [limitToPart, sourceSelection]);

  const handleSeek = (time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      videoRef.current.play().catch(() => {});
    }
  };

  const handleTimelineClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!timelineMapRef.current) return;
    const rect = timelineMapRef.current.getBoundingClientRect();
    const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    handleSeek(pos * duration);
  };

  if (!plan) return null;

  return (
    <section id="timeline-panel" className="panel timeline-panel">
      <div className="panel-heading">
        <h2 id="timeline-heading" className="panel-title">Таймлайн серии</h2>
        <div className="toolbar-actions">
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
            <input type="checkbox" id="analysis-debug" checked={showDebug} onChange={e => setShowDebug(e.target.checked)} /> Анализ
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
            <input type="checkbox" id="source-limit" checked={limitToPart} onChange={e => {
              const enabled = e.target.checked;
              setLimitToPart(enabled);
              const cuts = parts[selectedIndex]?.cuts;
              if (enabled && cuts?.length) {
                const start = cuts[0].start;
                setSourceSelection({ start, end: cuts[cuts.length - 1].end, retained: true });
                handleSeek(start);
              }
            }} /> В пределах части
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
            <input type="range" id="timeline-zoom" min="1" max="10" step="1" style={{ width: '100px' }} value={zoom} onChange={e => setZoom(Number(e.target.value))} /> Зум
          </label>
        </div>
      </div>
      <div className="timeline-scroll">
        <div id="timeline-map" className="timeline-map" style={{ width: `${zoom * 100}%` }} ref={timelineMapRef} onClick={handleTimelineClick}>
          <div id="timeline-ruler" className="timeline-ruler">
            {Array.from({ length: 10 }).map((_, i) => (
              <span key={i} style={{ left: `${i * 10}%` }} className="timeline-mark">
                {sourceTime((duration * i) / 10).split('.')[0]}
              </span>
            ))}
          </div>
          <div id="timeline-groups" className="timeline-groups">
            {parts.map((part, i) => {
              if (part.cuts.length === 0) return null;
              const startCut = part.cuts[0].start;
              const endCut = part.cuts[part.cuts.length - 1].end;
              const left = (startCut / duration) * 100;
              const width = ((endCut - startCut) / duration) * 100;
              return (
                <button 
                  key={i} 
                  className="timeline-group" 
                  aria-label={`Часть ${String(i + 1).padStart(2, '0')}`}
                  title={`Часть ${String(i + 1).padStart(2, '0')} · ${sourceTime(startCut)}–${sourceTime(endCut)}`}
                  style={{ left: `${left}%`, width: `${width}%` }} 
                  aria-pressed={selectedIndex === i}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSourceSelection({ start: startCut, end: endCut, retained: true });
                    onSelectPart(i);
                    handleSeek(startCut);
                  }}
                >
                  <span className="timeline-group-label">{String(i + 1).padStart(2, '0')}</span>
                </button>
              );
            })}
          </div>
          <div className="timeline-line">
            <div id="timeline-overview" className="timeline-track">
              {pieces.map((piece, i) => {
                const left = (piece.start / duration) * 100;
                const width = ((piece.end - piece.start) / duration) * 100;
                const isActive = piece.partIndex === selectedIndex;
                return (
                  <div 
                    key={i} 
                    className={`timeline-fragment ${piece.retained ? 'retained-fragment' : 'removed-fragment'} ${isActive ? 'active' : ''}`} 
                    style={{ left: `${left}%`, width: `${width}%` }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSourceSelection(piece);
                      handleSeek(piece.start);
                      if (piece.partIndex !== null && piece.partIndex !== selectedIndex) {
                        onSelectPart(piece.partIndex);
                      }
                    }}
                    title={pieceLabel(piece)}
                  />
                );
              })}
            </div>
            {showDebug && debugPieces.length > 0 && (
              <div id="analysis-debug-lane" className="timeline-track debug-lane" style={{ height: `${(Math.max(...debugPieces.map(p => p.lane)) + 1) * 8}px` }}>
                {debugPieces.map(p => (
                  <button 
                    key={p.id} 
                    className="timeline-reason" 
                    style={{ left: `${(p.start / duration) * 100}%`, width: `${((p.end - p.start) / duration) * 100}%`, top: `${p.lane * 8}px` }}
                    data-kind={p.kind}
                    title={p.title}
                    onMouseEnter={() => setActiveDebugInfo(p)}
                    onClick={(e) => {
                      e.stopPropagation();
                      setActiveDebugInfo(p);
                      setSourceSelection({ start: p.start, end: p.end, retained: p.partIndex !== null });
                      handleSeek(p.start);
                    }}
                  />
                ))}
              </div>
            )}
            <div id="timeline-playhead" className="timeline-playhead" style={{ left: `${(currentTime / duration) * 100}%` }}></div>
          </div>
        </div>
      </div>
      <div id="source-panel-review" className="source-panel-review">
        {job && (
          <video 
            id="source-player" 
            className="source-player" 
            controls 
            playsInline
            ref={videoRef}
            src={`/api/jobs/${job.id}/source`}
            onError={() => setPlayerError(true)}
          ></video>
        )}
        {playerError && (
          <div className="message" style={{ color: 'var(--danger)', marginTop: '8px' }}>
            Браузер не смог открыть исходник. Для MKV может потребоваться локальный видеоплеер.
          </div>
        )}
        <div className="source-review-info">
          <div id="source-selection" className="source-selection">
            {sourceSelection && (
              <span className="muted" style={{ fontWeight: 600 }}>
                {sourceSelection.retained ? 'Оставлено' : 'Убрано'} · исходник {sourceTime(sourceSelection.start)}–{sourceTime(sourceSelection.end)}
              </span>
            )}
          </div>
          <button id="source-full-button" type="button" className="btn-text" hidden={!limitToPart} onClick={() => { setLimitToPart(false); setSourceSelection(null); }}>
            Смотреть всё
          </button>
          <div style={{ flex: 1 }}></div>
          {showDebug && activeDebugInfo && (
            <div id="analysis-debug-info" className="analysis-debug-info">
              <span className="badge" style={{ marginRight: '8px' }}>{DEBUG_KIND_LABELS[activeDebugInfo.kind] || activeDebugInfo.kind}</span>
              <span className="muted" style={{ marginRight: '8px' }}>{sourceTime(activeDebugInfo.start)}–{sourceTime(activeDebugInfo.end)}</span>
              <strong style={{ marginRight: '8px' }}>{activeDebugInfo.title}</strong>
              <span className="muted">{activeDebugInfo.detail}</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
