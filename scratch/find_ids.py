import re
app = open('app/static/app.js', encoding='utf-8').read()
lib = open('app/static/library.js', encoding='utf-8').read()
for name, text in [('app.js', app), ('library.js', lib)]:
    matches = re.findall(r"setText\(['\"](.*?)['\"]", text)
    print(name, set(matches))
