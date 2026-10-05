import re
from pathlib import Path

css_path = Path("app/static/style.css")
css = css_path.read_text("utf-8")

# Remove topbar styles completely
css = re.sub(r'\.topbar\{.*?\}', '', css, flags=re.DOTALL)

# Remove old review-workspace grid
css = re.sub(r'\.review-workspace\{display:grid;grid-template-columns:minmax\(0,1fr\) 310px;gap:24px;align-items:start\}', '', css)

# We can append new layout rules at the end of the file
new_css = """
/* --- NEW MODERN LAYOUT --- */
.app-layout {
  display: flex;
  min-height: 100vh;
  background: var(--bg);
}

.sidebar {
  width: 260px;
  background: rgba(15, 20, 30, 0.7);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-right: 1px solid rgba(255,255,255,0.05);
  display: flex;
  flex-direction: column;
  padding: 24px 20px;
  flex-shrink: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.5px;
  margin-bottom: 40px;
  color: #fff;
}

.sidebar nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar nav a {
  padding: 12px 16px;
  border-radius: 12px;
  color: var(--muted);
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s;
  display: flex;
  align-items: center;
}

.sidebar nav a:hover {
  background: rgba(255,255,255,0.05);
  color: #fff;
}

.sidebar nav .nav-active {
  background: rgba(56, 189, 248, 0.1);
  color: var(--accent);
}

.status-pill {
  margin-top: auto;
  padding: 12px 16px;
  background: rgba(0,0,0,0.2);
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.05);
}

.main-content {
  flex: 1;
  min-width: 0;
  height: 100vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

main.screen-shell {
  flex: 1;
  padding: 40px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}

.review-workspace {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.review-top-row {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(320px, 400px);
  gap: 24px;
}

.review-bottom-row {
  width: 100%;
}

.source-panel-review {
  display: flex;
  flex-direction: column;
}

.source-review {
  border-top: none;
  padding-top: 0;
}

/* Adjust timeline width to span fully */
#timeline-panel {
  width: 100%;
}

@media(max-width: 1100px) {
  .app-layout { flex-direction: column; }
  .sidebar { width: 100%; flex-direction: row; align-items: center; padding: 16px 24px; border-right: none; border-bottom: 1px solid rgba(255,255,255,0.05); }
  .brand { margin-bottom: 0; margin-right: 32px; }
  .sidebar nav { flex-direction: row; gap: 16px; margin-right: auto; }
  .status-pill { margin-top: 0; }
  .review-top-row { grid-template-columns: 1fr; }
}

@media(max-width: 800px) {
  main.screen-shell { padding: 20px; }
  .workspace { grid-template-columns: 1fr; }
}
"""

css += new_css

# Also update the workspace grid to be a nice 2-column or 3-column layout
# wait, .workspace is used in source-panel / processing-column / episode-guide
css = css.replace(
    ".workspace{display:grid;grid-template-columns:280px minmax(0,1fr) 340px;gap:24px;align-items:start}",
    ".workspace{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:32px;align-items:start}"
)

# And remove .media-column from the CSS? Or leave it as is if it falls back nicely.
# Edit screen layout: we have .episode-editor which is 
# .episode-editor{display:grid;grid-template-columns:minmax(340px,560px) minmax(0,1fr);gap:24px}
# Let's make it more balanced
css = css.replace(
    ".episode-editor{display:grid;grid-template-columns:minmax(340px,560px) minmax(0,1fr);gap:24px}",
    ".episode-editor{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(300px, 1fr);gap:32px}"
)

css_path.write_text(css, "utf-8")
print("Layout CSS applied!")
