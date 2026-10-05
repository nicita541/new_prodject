import re

app_js = open('app/static/app.js', 'r', encoding='utf-8').read()
lib_js = open('app/static/library.js', 'r', encoding='utf-8').read()
index_html = open('app/static/index.html', 'r', encoding='utf-8').read()
html_ids = set(re.findall(r'id=["\']([^"\']+)["\']', index_html))

# Look for any $(...) that isn't a plain literal
dynamic_calls = []
for fname, content in [('app.js', app_js), ('library.js', lib_js)]:
    matches = re.findall(r'\$\(([^)]+)\)', content)
    for m in matches:
        if not (m.startswith('"') or m.startswith("'")):
            dynamic_calls.append((fname, m))

print("Dynamic $() calls:")
for d in dynamic_calls:
    print(" ", d)
