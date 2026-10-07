import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Sidebar } from './components/common/Sidebar';
import { ProjectsPage } from './pages/ProjectsPage';
import { TrashPage } from './pages/TrashPage';
import { EpisodesPage } from './pages/EpisodesPage';
import { EditEpisodePage } from './pages/EditEpisodePage';
import { ReviewEpisodePage } from './pages/ReviewEpisodePage';

import { useEffect } from 'react';
import { redirectLegacyHash } from './navigation';

export default function App() {
  useEffect(() => {
    // Handle legacy hash routing
    redirectLegacyHash(window.location.hash, path => window.location.replace(path));
  }, []);

  return (
    <Router>
      <div className="app-layout">
        <Sidebar />
        
        <div className="main-content">
          <Routes>
            <Route path="/" element={<Navigate to="/projects" replace />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/trash" element={<TrashPage />} />
            <Route path="/project/:projectId" element={<EpisodesPage />} />
            <Route path="/episode/:episodeId/edit" element={<EditEpisodePage />} />
            <Route path="/episode/:episodeId/review/:jobId?" element={<ReviewEpisodePage />} />
          </Routes>
          
          <footer className="app-footer">
            <span style={{ fontWeight: 700, letterSpacing: '-0.2px', color: '#fff' }}>КАДР STUDIO</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="storage-badge" id="storage-title"></span>
              <span id="storage-description"></span>
            </div>
          </footer>
        </div>
      </div>
    </Router>
  );
}
