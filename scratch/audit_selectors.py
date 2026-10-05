import re

for fname in ['app/static/app.js', 'app/static/library.js']:
    content = open(fname, 'r', encoding='utf-8').read()
    qs = re.findall(r'querySelector(All)?\(["\']([^"\']+)["\']\)', content)
    print(f"=== {fname} querySelectors ===")
    for all_flag, sel in set(qs):
        print(f"  {sel} (all={bool(all_flag)})")
