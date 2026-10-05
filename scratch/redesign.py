import re
from pathlib import Path

css_path = Path("app/static/style.css")
css = css_path.read_text("utf-8")

# 1. Update Root Variables
new_root = """:root {
  --bg: #0b0f19;
  --panel: rgba(20, 24, 34, 0.65);
  --raised: #1c2230;
  --line: rgba(255, 255, 255, 0.08);
  --text: #f1f5f9;
  --muted: #94a3b8;
  --accent: #38bdf8;
  --accent-glow: rgba(56, 189, 248, 0.35);
  --green: #34d399;
  --red: #f87171;
  font-family: 'Inter', 'Segoe UI Variable', 'Segoe UI', system-ui, sans-serif;
  color: var(--text);
  background: var(--bg);
  font-synthesis: none;
  color-scheme: dark;
}

/* Custom Scrollbar */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.25); }

/* Global Smoothness */
* { transition: background-color 0.2s, border-color 0.2s, box-shadow 0.2s, transform 0.2s; }
.timeline-scroll * { transition: none; } /* Disable transition for timeline performance */
.timeline-playhead { transition: none; }
"""
css = re.sub(r":root\{.*?\}", new_root, css, flags=re.DOTALL)

# 2. Update Panels with Glassmorphism
css = css.replace(
    ".panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;min-width:0}",
    ".panel{background:var(--panel);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid var(--line);border-radius:16px;padding:24px;min-width:0;box-shadow:0 12px 32px rgba(0,0,0,0.2);}"
)
# And update project-card and episode-card
css = css.replace(
    ".project-card{display:flex;flex-direction:column;align-items:flex-start;min-height:245px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:24px}",
    ".project-card{display:flex;flex-direction:column;align-items:flex-start;min-height:245px;background:var(--panel);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid var(--line);border-radius:16px;padding:24px;box-shadow:0 8px 24px rgba(0,0,0,0.15);cursor:pointer;}"
)
css = css.replace(
    ".project-card:hover{border-color:#6786ad;background:#202631}",
    ".project-card:hover{border-color:var(--accent);background:rgba(25, 32, 45, 0.8);transform:translateY(-2px);box-shadow:0 12px 32px rgba(0,0,0,0.3);}"
)
css = css.replace(
    ".episode-card{background:var(--panel);border:1px solid var(--line);padding:24px;border-radius:12px}",
    ".episode-card{background:var(--panel);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid var(--line);padding:24px;border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,0.15);}"
)

# 3. Update Buttons
css = css.replace(
    ".primary-button{width:100%;border:0;border-radius:7px;padding:12px 14px;background:var(--accent);color:#1b2a40;font-weight:650;font-size:12px;text-align:center}",
    ".primary-button{width:100%;border:0;border-radius:10px;padding:12px 16px;background:linear-gradient(135deg, #0ea5e9, var(--accent));color:#fff;font-weight:600;font-size:13px;text-align:center;box-shadow:0 4px 14px var(--accent-glow);}"
)
css = css.replace(
    ".primary-button:disabled{background:#343e4d;color:#a9b3c2;opacity:1}",
    ".primary-button:disabled{background:#1e293b;color:#64748b;opacity:1;box-shadow:none;transform:none;cursor:not-allowed;}"
)
css = css.replace(
    ".secondary-button{display:inline-flex;align-items:center;justify-content:center;background:#242a35;border:1px solid #455066;border-radius:6px;color:var(--text);padding:9px 12px;font-size:11px}",
    ".secondary-button{display:inline-flex;align-items:center;justify-content:center;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:8px;color:var(--text);padding:9px 14px;font-size:12px;font-weight:500;backdrop-filter:blur(8px);}"
)
css = css.replace(
    ".secondary-button:hover{background:#303849}",
    ".secondary-button:hover{background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.2);}"
)

# 4. Update Inputs and Selects
css = css.replace(
    "select{width:100%;padding:10px 28px 10px 10px;border:1px solid var(--line);border-radius:7px;background:#13161d;color:var(--text);font-size:11px;text-overflow:ellipsis}",
    "select{width:100%;padding:12px 30px 12px 12px;border:1px solid rgba(255,255,255,0.1);border-radius:10px;background:rgba(15,20,30,0.6);color:var(--text);font-size:12px;text-overflow:ellipsis;backdrop-filter:blur(10px);}"
)
css = css.replace(
    ".library-form input,.episode-form input{width:100%;background:#13161d;border:1px solid var(--line);border-radius:7px;padding:11px;color:var(--text);font:inherit;font-size:12px}",
    ".library-form input,.episode-form input{width:100%;background:rgba(15,20,30,0.6);border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:12px;color:var(--text);font:inherit;font-size:13px;backdrop-filter:blur(10px);}"
)
css = css.replace(
    ".part-context textarea{width:100%;resize:vertical;margin:10px 0;background:#13161d;border:1px solid var(--line);border-radius:7px;padding:10px;color:var(--text);font:inherit;font-size:11px;line-height:1.7}",
    ".part-context textarea{width:100%;resize:vertical;margin:10px 0;background:rgba(15,20,30,0.6);border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:12px;color:var(--text);font:inherit;font-size:12px;line-height:1.7;backdrop-filter:blur(10px);}"
)

# 5. Topbar updates
css = css.replace(
    ".topbar{height:70px;padding:0 28px;display:flex;align-items:center;gap:36px;border-bottom:1px solid var(--line);background:#161920}",
    ".topbar{height:70px;padding:0 28px;display:flex;align-items:center;gap:36px;border-bottom:1px solid rgba(255,255,255,0.05);background:rgba(11,15,25,0.75);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);position:sticky;top:0;z-index:100;}"
)

# 6. Make brand cool
css = css.replace(
    ".brand-mark{height:31px;width:31px;display:grid;place-items:center;background:var(--accent);color:#182333;border-radius:7px;font-size:22px;letter-spacing:-2px}",
    ".brand-mark{height:34px;width:34px;display:grid;place-items:center;background:linear-gradient(135deg, var(--accent), #0284c7);color:#fff;border-radius:9px;font-size:22px;letter-spacing:-2px;box-shadow:0 4px 12px var(--accent-glow);}"
)

# 7. Upload Zone
css = css.replace(
    ".upload-zone{width:100%;display:flex;gap:12px;align-items:center;text-align:left;padding:16px 12px;border:1px dashed #506079;border-radius:9px;background:#20293650;color:var(--text);font-size:12px}",
    ".upload-zone{width:100%;display:flex;gap:16px;align-items:center;text-align:left;padding:24px 20px;border:2px dashed rgba(255,255,255,0.15);border-radius:12px;background:rgba(20,28,40,0.4);color:var(--text);font-size:13px;backdrop-filter:blur(10px);cursor:pointer;}"
)
css = css.replace(
    ".upload-zone:hover{", # doesn't exist, I'll add it to the previous line
    ""
)
css = css.replace(
    ".upload-zone.dragging{background:#a8c5ed20;border-color:var(--accent)}",
    ".upload-zone:hover,.upload-zone.dragging{background:rgba(56,189,248,0.08);border-color:var(--accent);}"
)

# Write it back
css_path.write_text(css, "utf-8")
print("CSS patched!")
