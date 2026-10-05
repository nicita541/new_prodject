import re

index_html = open('app/static/index.html', 'r', encoding='utf-8').read()
app_js = open('app/static/app.js', 'r', encoding='utf-8').read()
lib_js = open('app/static/library.js', 'r', encoding='utf-8').read()

# Extract all IDs from index.html
html_ids = set(re.findall(r'id=["\']([^"\']+)["\']', index_html))

# Extract all $('...') calls from app.js and lib.js
js_calls = set()
for content in [app_js, lib_js]:
    # Match $('something') or $("something")
    calls = re.findall(r'\$\(["\']([^"\']+)["\']\)', content)
    js_calls.update(calls)

missing_from_html = []
for cid in sorted(js_calls):
    if cid not in html_ids:
        missing_from_html.append(cid)

print("HTML IDs total:", len(html_ids))
print("JS dollar calls total:", len(js_calls))
print("MISSING FROM HTML:", missing_from_html)
