import urllib.request

try:
    with urllib.request.urlopen('http://127.0.0.1:8765/') as response:
        html = response.read().decode('utf-8')
        print('Server Status:', response.status)
        print('HTML bytes:', len(html))
        print('Has quality-warnings ID:', 'id="quality-warnings"' in html)
        print('Has quality-notes ID:', 'id="quality-notes"' in html)
        print('Has deepseek-config ID:', 'id="deepseek-config"' in html)
        print('Has history-count ID:', 'id="history-count"' in html)

    with urllib.request.urlopen('http://127.0.0.1:8765/static/style.css') as response:
        css = response.read().decode('utf-8')
        print('CSS Status:', response.status)
        print('CSS bytes:', len(css))
        print('Has .app-layout in CSS:', '.app-layout' in css)

    with urllib.request.urlopen('http://127.0.0.1:8765/api/library') as response:
        lib = response.read().decode('utf-8')
        print('API /api/library Status:', response.status)
        print('API /api/library bytes:', len(lib))

except Exception as e:
    print('Error testing server:', e)
