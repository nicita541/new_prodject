from pathlib import Path

css_path = Path("app/static/style.css")
css = css_path.read_text("utf-8")

extra_css = """
/* Shorts Side-by-Side Viewer */
.shorts-viewer-layout {
  display: grid;
  grid-template-columns: 230px minmax(0, 1fr);
  gap: 28px;
  align-items: start;
}

@media (max-width: 820px) {
  .shorts-viewer-layout {
    grid-template-columns: 1fr;
  }
}

.shorts-player-col {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.shorts-player-col .shorts-preview-box {
  width: 220px;
  max-width: 100%;
  aspect-ratio: 9/16;
  margin: 0;
  border-radius: 14px;
  overflow: hidden;
  background: #000;
  border: 2px solid rgba(255, 255, 255, 0.15);
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.7);
}

.shorts-playlist-col {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
"""

if ".shorts-viewer-layout" not in css:
    css += extra_css
    css_path.write_text(css, "utf-8")
    print("style.css updated with .shorts-viewer-layout")
else:
    print(".shorts-viewer-layout already in style.css")
