import { useRef, useEffect } from 'react';
import type { JobFile } from '../api/types';

interface VideoPlayerProps {
  file: JobFile | undefined;
}

export function VideoPlayer({ file }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      if (file?.url) {
        videoRef.current.src = file.url;
        videoRef.current.load();
      } else {
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
        loop
        style={{ width: '100%', height: '100%', backgroundColor: '#000' }}
      >
        {/* We can track subtitle here if needed, but legacy UI doesn't attach <track> to #player, just an external download link */}
      </video>
    </div>
  );
}
