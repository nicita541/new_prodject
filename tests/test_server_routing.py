"""Routes must expose the *actual* user-supplied Studio Edition interface.

Regression: the old catch-all served React index.html for every URL,
including studio-edition.html and the JavaScript bridge.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config
from app.server import app, create_app


client = TestClient(app, base_url="http://127.0.0.1")


def test_studio_routes_serve_exact_ui_or_explicit_build_error():
    dist = config.ROOT / "frontend" / "dist"
    built = all((dist / filename).is_file() for filename in (
        "studio-edition.html", "studio-live-bridge.js", "studio-edition.css", "studio-edition-app.js"))
    for route in ("/", "/projects", "/studio-edition.html"):
        response = client.get(route)
        if built:
            assert response.status_code == 200, (route, response.text[:120])
            assert "text/html" in response.headers["content-type"]
            assert "studio-live-bridge.js" in response.text
            # This is the static HTML entrypoint. The finishing workspace
            # is inserted dynamically by studio-edition-app.js, so it must
            # not be required in the initial HTML source.
            assert '<main id="main"' in response.text
            assert '<div id="root"></div>' not in response.text
        else:
            assert response.status_code == 503
            assert "Studio Edition не собрана" in response.json()["detail"]

    bridge = client.get("/studio-live-bridge.js")
    if built:
        assert bridge.status_code == 200
        assert "javascript" in bridge.headers["content-type"]
        assert "KadrBridge" in bridge.text
    else:
        assert bridge.status_code == 503

    if built:
        page = client.get("/studio-edition.html")
        assert '<link rel="stylesheet" href="/studio-edition.css">' in page.text
        assert '<script src="/studio-edition-app.js"></script>' in page.text
        assert "<style>" not in page.text
        assert "<script>" not in page.text
        # This CSP blocks inline script/style elements. Every executable
        # stylesheet and application script must therefore be fetched separately.
        policy = page.headers["content-security-policy"]
        assert "script-src 'self'" in policy
        assert "script-src 'self' 'unsafe-inline'" not in policy
        for asset, mimetype, snippet in (
            ("/studio-edition.css", "text/css", ".sidebar {"),
            ("/studio-edition-app.js", "javascript", "window.KadrBridge.refresh"),
        ):
            response = client.get(asset)
            assert response.status_code == 200, (asset, response.text[:100])
            assert mimetype in response.headers["content-type"]
            assert snippet in response.text
            if asset == "/studio-edition-app.js":
                # Prove that the shipped application contains the dynamic
                # finishing workspace rather than checking the raw HTML.
                # Browser smoke separately verifies runtime DOM insertion.
                assert 'fc-workspace' in response.text
            assert response.headers["cache-control"] == "no-store"
    else:
        assert client.get("/studio-edition.css").status_code == 503
        assert client.get("/studio-edition-app.js").status_code == 503


def test_active_server_identifies_loaded_backend_and_real_studio_assets():
    from app.studio_identity import server_identity
    response = client.get("/api/studio/identity")
    assert response.status_code == 200
    assert response.json() == server_identity()
    assert response.json()["application"] == "kadr-studio"
    assert response.json()["interface"] == "studio-edition"
    assert response.json()["backend"] is not None
    assert "workspace" in response.json()


def test_studio_deep_links_preserve_screen_and_identifiers():
    dist = config.ROOT / "frontend" / "dist"
    built = all((dist / filename).is_file() for filename in (
        "studio-edition.html", "studio-live-bridge.js", "studio-edition.css", "studio-edition-app.js"))
    cases = (
        ("/studio", "screen=finishing"),
        ("/trash", "screen=trash"),
        ("/api", "screen=api"),
        ("/project/123", "screen=episodes&project=123"),
        ("/episode/e1/edit", "screen=editor&episode=e1"),
        ("/episode/e1/review/j1", "screen=review&episode=e1&job=j1"),
        ("/episode/e1/finishing/j1", "screen=finishing&episode=e1&job=j1"),
    )
    for route, query in cases:
        response = client.get(route, follow_redirects=False)
        if not built:
            assert response.status_code == 503
        else:
            assert response.status_code == 307, route
            assert response.headers["location"] == "/studio-edition.html?" + query


def test_canonical_studio_is_not_silent_react_fallback():
    # Logging is process-wide. Initialize it before patching the UI root so
    # Windows temp cleanup does not encounter an open session log handle.
    from app.run_logging import configure_logging
    configure_logging("tests")
    with TemporaryDirectory() as root:
        dist = Path(root) / "frontend" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
        (dist / "studio-edition.html").write_text(
            '<!doctype html><link rel="stylesheet" href="/studio-edition.css">'
            '<script src="/studio-live-bridge.js"></script>'
            '<script src="/studio-edition-app.js"></script>'
            '<main class="fc-workspace">Reference design</main>', encoding="utf-8")
        (dist / "studio-edition.css").write_text(
            '.sidebar{display:flex}', encoding="utf-8")
        (dist / "studio-edition-app.js").write_text(
            "document.body.dataset.studio='ready';", encoding="utf-8")
        (dist / "studio-live-bridge.js").write_text(
            "window.KadrBridge={};", encoding="utf-8")
        with patch.object(config, "ROOT", Path(root)):
            local_app = create_app()
            with TestClient(local_app, base_url="http://127.0.0.1") as c:
                for route in ("/", "/projects", "/studio-edition.html"):
                    result = c.get(route)
                    assert result.status_code == 200
                    assert "Reference design" in result.text
                    assert 'id="root"' not in result.text
                result = c.get("/studio-live-bridge.js")
                assert result.status_code == 200
                assert "KadrBridge" in result.text
                assert result.headers["cache-control"] == "no-cache"
                assert c.get("/studio-edition.css").status_code == 200
                assert c.get("/studio-edition-app.js").status_code == 200
                assert c.get("/nothing").status_code == 404


def test_removed_interfaces_are_unavailable():
    for path in ('/legacy','/react-debug','/studio-edition-reference.html'):
        assert client.get(path).status_code == 404


def test_api_404_returns_json_not_html():
    response = client.get("/api/not-found-endpoint")
    assert response.status_code == 404
    assert "application/json" in response.headers["content-type"]


def test_static_files():
    response = client.get("/static/style.css")
    assert response.status_code == 404
