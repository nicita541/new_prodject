import { useRef, useEffect } from 'react';
import type { JobFile } from '../api/types';

interface VideoPlayerProps {
  file: JobFile | undefined;
  onEnded?: () => void;
}

export function VideoPlayer({ file, onEnded }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const resumeNextRef = useRef(false);

  useEffect(() => {
    if (videoRef.current) {
      if (file?.url) {
        videoRef.current.src = file.url;
        videoRef.current.load();
        if (resumeNextRef.current) {
          resumeNextRef.current = false;
          videoRef.current.play().catch(() => {});
        }
      } else {
        resumeNextRef.current = false;
        videoRef.current.removeAttribute('src');
        videoRef.current.load();
      }
    }
  }, [file?.url]);

  return (
    <div className="shorts-preview-box">
      <video 
        ref={videoRef}
        id="player" 
        controls 
        playsInline 
        preload="metadata" 
        onEnded={() => {
          if (onEnded) {
            resumeNextRef.current = true;
            onEnded();
          }
        }}
        style={{ width: '100%', height: '100%', backgroundColor: '#000' }}
      >
        {/* We can track subtitle here if needed, but legacy UI doesn't attach <track> to #player, just an external download link */}
      </video>
    </div>
  );
}
