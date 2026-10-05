import re
from pathlib import Path

# 1. NEW STYLE.CSS
css = """@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --bg-base: #09090b;
  --bg-sidebar: #121214;
  --bg-panel: #18181b;
  --bg-card: #27272a;
  --bg-hover: #3f3f46;
  --border-light: rgba(255, 255, 255, 0.06);
  --border-strong: rgba(255, 255, 255, 0.15);
  --text-primary: #f8fafc;
  --text-secondary: #a1a1aa;
  --accent: #6366f1;
  --accent-hover: #4f46e5;
  --accent-glow: rgba(99, 102, 241, 0.4);
  --danger: #ef4444;
  --success: #10b981;
  --radius-sm: 6px;
  --radius-md: 12px;
  --radius-lg: 18px;
  --shadow-sm: 0 4px 6px -1px rgba(0,0,0,0.3);
  --shadow-lg: 0 10px 30px -5px rgba(0,0,0,0.5);
  font-family: 'Inter', -apple-system, sans-serif;
  color: var(--text-primary);
  background: var(--bg-base);
  color-scheme: dark;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body { margin: 0; overflow: hidden; }
a { color: inherit; text-decoration: none; }
button, input, select { font: inherit; color: inherit; }
button { cursor: pointer; border: none; background: none; }
[hidden] { display: none !important; }

/* Scrollbars */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--bg-hover); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-secondary); }

/* Buttons */
.btn-primary { background: linear-gradient(135deg, var(--accent), var(--accent-hover)); color: #fff; padding: 10px 18px; border-radius: var(--radius-md); font-weight: 600; font-size: 13px; box-shadow: var(--shadow-sm), 0 0 12px var(--accent-glow); transition: all 0.2s; }
.btn-primary:hover:not(:disabled) { filter: brightness(1.15); transform: translateY(-1px); box-shadow: var(--shadow-lg), 0 0 20px var(--accent-glow); }
.btn-primary:disabled { background: var(--bg-hover); color: var(--text-secondary); box-shadow: none; cursor: not-allowed; }

.btn-secondary { background: var(--bg-card); border: 1px solid var(--border-strong); padding: 8px 14px; border-radius: var(--radius-md); font-size: 12px; font-weight: 500; transition: all 0.2s; display: inline-flex; align-items: center; justify-content: center; }
.btn-secondary:hover { background: var(--bg-hover); }

.btn-danger { background: transparent; border: 1px solid rgba(239, 68, 68, 0.4); color: var(--danger); padding: 8px 14px; border-radius: var(--radius-md); font-size: 12px; font-weight: 500; transition: all 0.2s; }
.btn-danger:hover { background: rgba(239, 68, 68, 0.1); border-color: var(--danger); }

.btn-text { color: var(--accent); font-size: 12px; font-weight: 500; }
.btn-text:hover { text-decoration: underline; }

/* Inputs & Forms */
.form-group { margin-bottom: 20px; }
.form-label { display: block; font-size: 12px; font-weight: 500; color: var(--text-secondary); margin-bottom: 8px; }
.form-input, .form-select { width: 100%; background: #000; border: 1px solid var(--border-strong); padding: 12px 14px; border-radius: var(--radius-md); font-size: 13px; transition: all 0.2s; outline: none; }
.form-input:focus, .form-select:focus { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-glow); }

/* Layout */
.app-layout { display: flex; height: 100vh; overflow: hidden; }
.sidebar { width: 260px; background: var(--bg-sidebar); border-right: 1px solid var(--border-light); display: flex; flex-direction: column; padding: 24px; flex-shrink: 0; }
.brand { font-size: 20px; font-weight: 700; display: flex; align-items: center; gap: 12px; margin-bottom: 48px; letter-spacing: -0.5px; }
.brand-mark { width: 32px; height: 32px; background: linear-gradient(135deg, var(--accent), #a855f7); border-radius: 8px; display: grid; place-items: center; font-size: 18px; color: #fff; box-shadow: 0 4px 12px rgba(168, 85, 247, 0.3); }
.nav-menu { display: flex; flex-direction: column; gap: 8px; }
.nav-link { padding: 10px 14px; border-radius: var(--radius-md); color: var(--text-secondary); font-size: 14px; font-weight: 500; transition: all 0.2s; display: flex; align-items: center; gap: 12px; }
.nav-link:hover { background: var(--border-light); color: var(--text-primary); }
.nav-active { background: var(--accent-glow); color: var(--accent); border: 1px solid rgba(99, 102, 241, 0.2); }
.status-pill { margin-top: auto; padding: 12px; border-radius: var(--radius-md); background: rgba(0,0,0,0.3); border: 1px solid var(--border-light); font-size: 11px; display: flex; align-items: center; gap: 8px; color: var(--text-secondary); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-secondary); box-shadow: 0 0 8px currentColor; }
.ready .status-dot { background: var(--success); }
.offline .status-dot { background: var(--danger); }

.main-content { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow-y: auto; position: relative; }
.screen-shell { padding: 40px; max-width: 1600px; margin: 0 auto; width: 100%; }

/* Typography & Headings */
.page-title { font-size: 32px; font-weight: 700; letter-spacing: -1px; margin-bottom: 8px; }
.page-desc { font-size: 14px; color: var(--text-secondary); margin-bottom: 32px; line-height: 1.6; max-width: 600px; }
.eyebrow { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: var(--accent); margin-bottom: 8px; }
.muted { color: var(--text-secondary); }
.small { font-size: 12px; line-height: 1.5; }

/* Breadcrumbs & Toolbar */
.breadcrumbs { display: flex; align-items: center; gap: 12px; font-size: 13px; color: var(--text-secondary); margin-bottom: 32px; font-weight: 500; }
.breadcrumbs a:hover { color: var(--text-primary); }
.breadcrumbs a+a:before { content: '/'; margin-right: 12px; opacity: 0.3; }
.screen-toolbar { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 32px; }

/* Panels */
.panel { background: var(--bg-panel); border: 1px solid var(--border-light); border-radius: var(--radius-lg); padding: 24px; box-shadow: var(--shadow-sm); }
.panel-heading { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
.panel-title { font-size: 18px; font-weight: 600; letter-spacing: -0.5px; }

/* Grids & Cards */
.grid-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
.item-card { background: var(--bg-panel); border: 1px solid var(--border-light); border-radius: var(--radius-lg); padding: 24px; display: flex; flex-direction: column; min-height: 220px; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); position: relative; }
.item-card:hover { transform: translateY(-4px); box-shadow: var(--shadow-lg); border-color: var(--border-strong); background: var(--bg-card); }
.card-icon { width: 48px; height: 48px; border-radius: 12px; display: grid; place-items: center; font-size: 24px; margin-bottom: 20px; background: rgba(255,255,255,0.03); border: 1px solid var(--border-light); }
.card-title { font-size: 18px; font-weight: 600; margin-bottom: 8px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; line-height: 1.3; }
.card-meta { font-size: 12px; color: var(--text-secondary); margin-bottom: auto; }
.card-actions { display: flex; align-items: center; gap: 12px; margin-top: 24px; }

/* Episode Editor specific */
.editor-layout { display: grid; grid-template-columns: minmax(400px, 1.5fr) minmax(300px, 1fr); gap: 32px; align-items: start; }
.upload-zone { width: 100%; border: 2px dashed var(--border-strong); border-radius: var(--radius-md); padding: 32px 24px; text-align: center; background: rgba(255,255,255,0.02); transition: all 0.2s; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 12px; }
.upload-zone:hover { border-color: var(--accent); background: var(--accent-glow); }
.upload-icon { font-size: 32px; color: var(--accent); }
.upload-text { font-size: 14px; font-weight: 500; }
.upload-hint { font-size: 12px; color: var(--text-secondary); }

/* Settings Sections */
.settings-group { margin-top: 24px; padding-top: 24px; border-top: 1px solid var(--border-light); }
.settings-summary { font-size: 14px; font-weight: 600; display: flex; justify-content: space-between; cursor: pointer; list-style: none; align-items: center; }
.settings-summary::-webkit-details-marker { display: none; }
.settings-summary:after { content: '+'; font-size: 18px; color: var(--text-secondary); }
details[open] .settings-summary:after { content: '−'; }
.settings-content { margin-top: 20px; display: grid; gap: 16px; }

/* Review Screen (NLE Layout) */
.review-top-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 400px); gap: 24px; margin-bottom: 24px; }
.player-container { width: 100%; aspect-ratio: 16/9; background: #000; border-radius: var(--radius-md); overflow: hidden; border: 1px solid var(--border-strong); box-shadow: var(--shadow-lg); }
video { width: 100%; height: 100%; outline: none; }
.playlist-panel { display: flex; flex-direction: column; gap: 16px; }
.playlist-list { display: flex; flex-direction: column; gap: 8px; max-height: 300px; overflow-y: auto; padding-right: 8px; }
.playlist-item { display: flex; justify-content: space-between; padding: 12px; background: var(--bg-card); border-radius: var(--radius-sm); border: 1px solid var(--border-light); font-size: 12px; cursor: pointer; transition: all 0.2s; }
.playlist-item:hover { border-color: var(--border-strong); }
.playlist-item.selected { background: rgba(99,102,241,0.15); border-color: var(--accent); box-shadow: 0 0 12px var(--accent-glow); }

/* Timeline */
.timeline-panel { width: 100%; }
.timeline-tools { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.timeline-scroll { width: 100%; overflow-x: auto; padding-bottom: 16px; }
.timeline-map { min-width: 100%; position: relative; }
.timeline-ruler { display: flex; justify-content: space-between; font-size: 10px; color: var(--text-secondary); font-variant-numeric: tabular-nums; margin-bottom: 8px; }
.timeline-groups { height: 30px; position: relative; }
.timeline-group { position: absolute; top: 0; bottom: 0; background: rgba(255,255,255,0.05); border: 1px solid var(--border-light); border-radius: 4px; font-size: 10px; display: grid; place-items: center; cursor: pointer; }
.timeline-group.selected { background: var(--accent-glow); border-color: var(--accent); color: #fff; }
.timeline-line { position: relative; margin-top: 4px; }
.timeline-track { height: 40px; background: #000; border-radius: var(--radius-sm); position: relative; overflow: visible; box-shadow: inset 0 2px 8px rgba(0,0,0,0.5); border: 1px solid var(--border-strong); }
.timeline-piece { position: absolute; top: 0; bottom: 0; border: 1px solid rgba(0,0,0,0.5); background: #3f3f46; transition: filter 0.2s; cursor: pointer; }
.timeline-piece.removed { background: repeating-linear-gradient(45deg, rgba(255,255,255,0.05), rgba(255,255,255,0.05) 4px, transparent 4px, transparent 8px); opacity: 0.5; border: none; }
.timeline-piece:hover { filter: brightness(1.3); z-index: 2; border: 1px solid #fff; }
.timeline-playhead { position: absolute; top: -10px; bottom: -10px; width: 2px; background: var(--accent); z-index: 10; pointer-events: none; box-shadow: 0 0 10px var(--accent); }
.timeline-playhead:before { content: ''; position: absolute; top: 0; left: -4px; border: 5px solid transparent; border-top-color: var(--accent); }

/* Stages & Progress */
.progress-bar-bg { width: 100%; height: 6px; background: var(--bg-card); border-radius: 3px; overflow: hidden; margin: 12px 0; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), #a855f7); border-radius: 3px; transition: width 0.3s; }
.stages-list { display: flex; flex-direction: column; gap: 8px; margin-top: 24px; }
.stage-item { display: flex; align-items: center; gap: 12px; padding: 12px; background: rgba(255,255,255,0.02); border: 1px solid var(--border-light); border-radius: var(--radius-md); font-size: 12px; color: var(--text-secondary); }
.stage-item.current { background: rgba(99,102,241,0.1); border-color: rgba(99,102,241,0.3); color: #fff; }
.stage-item.done { color: var(--success); }
.stage-icon { width: 24px; height: 24px; border-radius: 50%; border: 1px solid currentColor; display: grid; place-items: center; flex-shrink: 0; }
.stage-item.done .stage-icon { background: rgba(16, 185, 129, 0.1); border-color: var(--success); }
.stage-item.current .stage-icon { background: var(--accent-glow); border-color: var(--accent); animation: pulse 2s infinite; }

@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(99,102,241,0.4); } 70% { box-shadow: 0 0 0 8px rgba(99,102,241,0); } 100% { box-shadow: 0 0 0 0 rgba(99,102,241,0); } }

/* Modifiers */
.message { font-size: 12px; padding: 12px; background: rgba(255,255,255,0.05); border-radius: var(--radius-sm); margin-top: 12px; }
.notice { background: rgba(99,102,241,0.1); border: 1px solid rgba(99,102,241,0.2); padding: 16px; border-radius: var(--radius-md); font-size: 13px; margin-top: 16px; }
.empty-state { text-align: center; padding: 64px 24px; border: 2px dashed var(--border-strong); border-radius: var(--radius-lg); color: var(--text-secondary); }

/* specific ID overrides */
#layout-description { font-size: 11px; margin-top: 6px; }
.part-context textarea { background: var(--bg-base); font-family: inherit; }
"""

css_path = Path("app/static/style.css")
css_path.write_text(css, "utf-8")
print("CSS completely rewritten")
