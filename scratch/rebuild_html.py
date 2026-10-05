import re
from pathlib import Path

html_path = Path("app/static/index.html")
html = html_path.read_text("utf-8")

# Extract major blocks
def extract_id(id_name):
    pattern = f'id="{id_name}"'
    match = re.search(f'<[^>]+{pattern}[^>]*>', html)
    if not match: return ""
    start = match.start()
    tag = match.group().split()[0][1:]
    
    # Simple nested tag extractor
    depth = 0
    i = start
    while i < len(html):
        if html[i:i+len(tag)+1] == f"<{tag}":
            # wait, need word boundary
            if not html[i:i+len(tag)+2].isalpha():
                depth += 1
        elif html[i:i+len(tag)+3] == f"</{tag}>":
            depth -= 1
            if depth == 0:
                return html[start:i+len(tag)+3]
        i += 1
    return html[start:]

def extract_class(cls_name, tag):
    pattern = f'class="[^"]*{cls_name}[^"]*"'
    match = re.search(f'<{tag}[^>]+{pattern}[^>]*>', html)
    if not match: return ""
    start = match.start()
    depth = 0
    i = start
    while i < len(html):
        if html.startswith(f"<{tag}", i) and not html[i:i+len(tag)+2].isalpha():
            depth += 1
        elif html.startswith(f"</{tag}>", i):
            depth -= 1
            if depth == 0:
                return html[start:i+len(tag)+3]
        i += 1
    return html[start:]

# We'll use regex replacements instead of full extraction to be safer.

# 1. Sidebar redesign
# Replace topbar with sidebar
html = html.replace('<header class="topbar">', '<div class="app-layout"><aside class="sidebar">')
html = html.replace('</header>', '</aside><div class="main-content">')
# Close app-layout and main-content at the very end before footer
html = html.replace('</main><footer>', '</main><footer>') # wait, need to close them properly
html = html.replace('</body>', '</div></div></body>')

# Move footer inside main-content
html = html.replace('</main><footer>', '</main>\n<footer>')
html = html.replace('</footer>\n</body>', '</footer>\n</div></div>\n</body>')

# 2. Extract source-assembly from timeline-panel
source_assembly_match = re.search(r'<div class="source-assembly">.*?</button><p id="source-error" class="message" role="status"></p></div>\s*</div>', html, re.DOTALL)
if source_assembly_match:
    source_assembly = source_assembly_match.group()
    html = html.replace(source_assembly, '')
    
    # Put source-assembly right before results-panel
    results_panel_match = re.search(r'<section id="results-panel" class="panel"[^>]*>', html)
    if results_panel_match:
        html = html.replace(results_panel_match.group(), f'<section id="source-panel-review" class="panel source-panel-review">\n{source_assembly}\n</section>\n' + results_panel_match.group())

# 3. Add a wrapper around source-panel-review and results-panel
html = html.replace('<section id="source-panel-review"', '<div class="review-top-row">\n<section id="source-panel-review"')
html = html.replace('</section></div><p id="review-empty"', '</section>\n</div>\n</div><p id="review-empty"')
# Wait, let's just do it with CSS!
html_path.write_text(html, "utf-8")
print("HTML structurally updated")
