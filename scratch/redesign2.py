import re
from pathlib import Path

css_path = Path("app/static/style.css")
css = css_path.read_text("utf-8")

# Video frame enhancements
css = css.replace(
    ".video-frame{width:100%;max-width:248px;aspect-ratio:9/16;background:#08090d;border-radius:8px;overflow:hidden;margin:auto;border:1px solid #3c4452}",
    ".video-frame{width:100%;max-width:260px;aspect-ratio:9/16;background:#000;border-radius:16px;overflow:hidden;margin:auto;border:1px solid rgba(255,255,255,0.1);box-shadow:0 12px 32px rgba(0,0,0,0.4);}"
)
css = css.replace(
    "#source-player{width:100%;aspect-ratio:16/9;height:auto;background:black;border-radius:8px;display:block}",
    "#source-player{width:100%;aspect-ratio:16/9;height:auto;background:black;border-radius:12px;display:block;border:1px solid rgba(255,255,255,0.1);box-shadow:0 8px 24px rgba(0,0,0,0.3);}"
)

# Playlist enhancements
css = css.replace(
    ".playlist button{width:100%;display:flex;justify-content:space-between;align-items:center;gap:8px;border:1px solid var(--line);background:#20252e;color:var(--muted);padding:9px 8px;border-radius:5px;font-size:10px}",
    ".playlist button{width:100%;display:flex;justify-content:space-between;align-items:center;gap:8px;border:1px solid rgba(255,255,255,0.05);background:rgba(20,25,35,0.6);color:var(--muted);padding:12px 10px;border-radius:8px;font-size:11px;backdrop-filter:blur(10px);}"
)
css = css.replace(
    ".playlist button.selected{background:#2b3b52;border-color:#6b8fbe;color:#d8e8ff}",
    ".playlist button.selected{background:rgba(56,189,248,0.15);border-color:var(--accent);color:#fff;box-shadow:0 4px 12px var(--accent-glow);}"
)

# Timeline enhancements
css = css.replace(
    ".timeline-group{position:absolute;top:0;bottom:-4px;background:#24242c;border:1px solid;border-bottom:0;padding:3px 0 7px;overflow:hidden;text-align:center;font-size:10px;white-space:nowrap}",
    ".timeline-group{position:absolute;top:0;bottom:-4px;background:rgba(30,35,45,0.8);border:1px solid rgba(255,255,255,0.1);border-bottom:0;border-radius:4px 4px 0 0;padding:4px 0 6px;overflow:hidden;text-align:center;font-size:10px;white-space:nowrap;color:var(--muted);backdrop-filter:blur(4px);}"
)
css = css.replace(
    ".timeline-group:hover,.timeline-group:focus-visible{background:#343440;z-index:2}",
    ".timeline-group:hover,.timeline-group:focus-visible{background:rgba(50,60,75,0.9);color:#fff;z-index:2;border-color:rgba(255,255,255,0.3);}"
)
css = css.replace(
    ".timeline-group.selected{background:#293748}",
    ".timeline-group.selected{background:rgba(56,189,248,0.2);color:#fff;border-color:var(--accent);}"
)
css = css.replace(
    ".timeline-track{height:32px;position:relative;background:#24242c;border-radius:3px;overflow:visible}",
    ".timeline-track{height:36px;position:relative;background:rgba(20,25,35,0.8);border-radius:6px;overflow:visible;box-shadow:inset 0 2px 4px rgba(0,0,0,0.2);}"
)
css = css.replace(
    ".timeline-piece.removed{background:repeating-linear-gradient(135deg,#45454e,#45454e 4px,#33333c 4px,#33333c 8px)}",
    ".timeline-piece.removed{background:repeating-linear-gradient(135deg,rgba(255,255,255,0.1),rgba(255,255,255,0.1) 4px,transparent 4px,transparent 8px);opacity:0.6;}"
)

# Text and layout tweaks
css = css.replace(
    "h1{font-size:25px;letter-spacing:-.6px;font-weight:600;margin:0}",
    "h1{font-size:28px;letter-spacing:-0.5px;font-weight:700;margin:0;color:#fff;}"
)
css = css.replace(
    "h2{font-size:15px;font-weight:600;margin:0}",
    "h2{font-size:18px;font-weight:600;margin:0;color:#fff;letter-spacing:-0.3px;}"
)

# Workspace gap
css = css.replace(
    ".workspace{display:grid;grid-template-columns:270px minmax(0,1fr) 310px;gap:18px;align-items:start}",
    ".workspace{display:grid;grid-template-columns:280px minmax(0,1fr) 340px;gap:24px;align-items:start}"
)

# Music slider
css = css.replace(
    ".music-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:15px;height:15px;border-radius:50%;background:var(--accent);border:0;cursor:pointer}",
    ".music-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:16px;height:16px;border-radius:50%;background:var(--accent);border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.4);cursor:pointer;}"
)

# Progress bar
css = css.replace(
    "progress::-webkit-progress-bar{background:var(--line)}",
    "progress::-webkit-progress-bar{background:rgba(255,255,255,0.05);border-radius:4px;}"
)
css = css.replace(
    "progress::-webkit-progress-value{background:var(--accent)}",
    "progress::-webkit-progress-value{background:linear-gradient(90deg, var(--accent), #0ea5e9);border-radius:4px;box-shadow:0 0 10px var(--accent-glow);}"
)
css = css.replace(
    "progress{appearance:none;-webkit-appearance:none;width:100%;height:4px;display:block;overflow:hidden;border:0;border-radius:2px;background:var(--line)}",
    "progress{appearance:none;-webkit-appearance:none;width:100%;height:6px;display:block;border:0;border-radius:4px;background:transparent;}"
)

# Write it back
css_path.write_text(css, "utf-8")
print("CSS patched again!")
