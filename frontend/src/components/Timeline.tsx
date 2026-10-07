import { useState, useRef, useEffect } from 'react';
import type { Plan, Job } from '../api/types';

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
  
  const videoRef = useRef<HTMLVideoElement>(null);
  const timelineMapRef = useRef<HTMLDivElement>(null);

  if (!plan) return null;

  const duration = plan.source?.duration || 1;
  const parts = plan.parts || [];
  
  // Handlers for interacting with the player
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      if (limitToPart && parts[selectedIndex]) {
        // Enforce boundary
        const cuts = parts[selectedIndex].cuts;
        const currentCut = cuts.find(c => video.currentTime >= c.start && video.currentTime <= c.end);
        if (!currentCut) {
          // If we leave the cut, pause or jump to the next cut within the part
          video.pause();
        }
      }
    };

    video.addEventListener('timeupdate', handleTimeUpdate);
    return () => video.removeEventListener('timeupdate', handleTimeUpdate);
  }, [limitToPart, selectedIndex, parts]);

  const handleSeek = (time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      videoRef.current.play().catch(() => {});
    }
  };

  const handleTimelineClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!timelineMapRef.current) return;
    const rect = timelineMapRef.current.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    handleSeek(pos * duration);
  };

  return (
    <section id="timeline-panel" className="panel timeline-panel">
      <div className="panel-heading">
        <h2 id="timeline-heading" className="panel-title">Таймлайн серии</h2>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
            <input type="checkbox" id="analysis-debug" checked={showDebug} onChange={e => setShowDebug(e.target.checked)} /> Анализ
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
            <input type="checkbox" id="source-limit" checked={limitToPart} onChange={e => setLimitToPart(e.target.checked)} /> В пределах части
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
            <input type="range" id="timeline-zoom" min="1" max="10" step="1" style={{ width: '100px' }} value={zoom} onChange={e => setZoom(Number(e.target.value))} /> Зум
          </label>
        </div>
      </div>
      <div className="timeline-scroll">
        <div id="timeline-map" className="timeline-map" style={{ width: `${zoom * 100}%` }} ref={timelineMapRef} onClick={handleTimelineClick}>
          <div id="timeline-ruler" className="timeline-ruler">
            {/* Simple ruler markers */}
            {Array.from({ length: 10 }).map((_, i) => (
              <span key={i} style={{ left: `${i * 10}%` }} className="timeline-mark">
                {Math.floor((duration * i) / 10)}s
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
                  style={{ left: `${left}%`, width: `${width}%` }} 
                  aria-pressed={selectedIndex === i}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectPart(i);
                    handleSeek(startCut);
                  }}
                >
                  <span className="timeline-group-label">Часть {String(i + 1).padStart(2, '0')}</span>
                </button>
              );
            })}
          </div>
          <div className="timeline-line">
            <div id="timeline-overview" className="timeline-track">
              {/* Show retained vs removed ranges based on cuts */}
              {parts.map((part, i) => (
                part.cuts.map((cut, j) => (
                  <div 
                    key={`${i}-${j}`} 
                    className={`timeline-fragment retained-fragment ${selectedIndex === i ? 'active' : ''}`} 
                    style={{ left: `${(cut.start / duration) * 100}%`, width: `${((cut.end - cut.start) / duration) * 100}%` }}
                  />
                ))
              ))}
            </div>
            {showDebug && plan.debug_timeline?.reasons && (
              <div id="analysis-debug-lane" className="timeline-track debug-lane">
                {plan.debug_timeline.reasons.map((reason, i) => {
                  const left = (reason.start / duration) * 100;
                  const width = ((reason.end - reason.start) / duration) * 100;
                  return (
                    <button 
                      key={i} 
                      className="timeline-reason" 
                      style={{ left: `${left}%`, width: `${width}%` }}
                      data-kind={reason.kind}
                      title={reason.title}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSeek(reason.start);
                      }}
                    />
                  );
                })}
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
            src={`/api/jobs/${job.id}/source`} // Using standard backend route
          ></video>
        )}
        <div className="source-review-info">
          <div id="source-selection" className="source-selection">
            {/* Show info about current time mapped to cut */}
          </div>
          <button id="source-full-button" type="button" className="btn-text" hidden={!limitToPart} onClick={() => setLimitToPart(false)}>
            Смотреть всё
          </button>
          <div style={{ flex: 1 }}></div>
          {showDebug && (
            <div id="analysis-debug-info" className="analysis-debug-info">
              {/* Currently hovered/clicked debug reason */}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
