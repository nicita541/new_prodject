import re
from pathlib import Path

html_path = Path("app/static/index.html")
html = html_path.read_text("utf-8")

# Find source-assembly block
source_regex = r'<div class="source-assembly">.*?<p id="source-error" class="message" role="status"></p></div>\s*</div>'
source_match = re.search(source_regex, html, flags=re.DOTALL)
if source_match:
    source_html = source_match.group(0)
    # Remove from original location
    html = html.replace(source_html, "")
    
    # We want to create:
    # <div class="review-workspace">
    #   <div class="review-top-row">
    #     <section id="source-panel-review" class="panel source-panel-review">
    #       [source_html]
    #     </section>
    #     <section id="results-panel" class="panel"...>
    #       ...
    #     </section>
    #   </div>
    #   <div class="review-bottom-row">
    #     <section id="timeline-panel" class="panel"...>
    #       ...
    #     </section>
    #   </div>
    # </div>
    
    # Wait, the structure in HTML right now is:
    # <div class="review-workspace"><section id="timeline-panel"...> ... </section><section id="results-panel"...> ... </section></div>
    
    # Let's extract timeline-panel fully
    timeline_regex = r'<section id="timeline-panel".*?</section>'
    # The previous regex removes source_assembly, so we do it AFTER removing it
    timeline_match = re.search(timeline_regex, html, flags=re.DOTALL)
    if timeline_match:
        timeline_html = timeline_match.group(0)
        
        # Now extract results-panel
        results_regex = r'<section id="results-panel".*?</section>'
        results_match = re.search(results_regex, html, flags=re.DOTALL)
        if results_match:
            results_html = results_match.group(0)
            
            # Now find review-workspace start and end
            workspace_regex = r'<div class="review-workspace">.*?</section></div>'
            workspace_match = re.search(workspace_regex, html, flags=re.DOTALL)
            
            if workspace_match:
                new_workspace = f"""<div class="review-workspace">
  <div class="review-top-row">
    <section id="source-panel-review" class="panel source-panel-review">
      <div class="panel-heading"><div><p class="eyebrow">ИСХОДНИК</p><h2>Просмотр оригинала</h2></div><span class="muted small">MP4 / MKV</span></div>
      {source_html}
    </section>
    {results_html}
  </div>
  <div class="review-bottom-row">
    {timeline_html}
  </div>
</div>"""
                html = html.replace(workspace_match.group(0), new_workspace)
                
html_path.write_text(html, "utf-8")
print("HTML review screen restructured!")
