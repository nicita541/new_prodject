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
    built = (dist / "studio-edition.html").is_file() and (dist / "studio-live-bridge.js").is_file()
    for route in ("/", "/projects", "/studio-edition.html"):
        response = client.get(route)
        if built:
            assert response.status_code == 200, (route, response.text[:120])
            assert "text/html" in response.headers["content-type"]
            assert "studio-live-bridge.js" in response.text
            assert "fc-workspace" in response.text
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
    built = (dist / "studio-edition.html").is_file() and (dist / "studio-live-bridge.js").is_file()
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
    with TemporaryDirectory() as root:
        dist = Path(root) / "frontend" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
        (dist / "studio-edition.html").write_text(
            '<!doctype html><script src="/studio-live-bridge.js"></script>'
            '<main class="fc-workspace">Reference design</main>', encoding="utf-8")
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
                assert c.get("/nothing").status_code == 404


def test_legacy_route_serves_legacy_index():
    response = client.get("/legacy")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "app.js" in response.text or "library.js" in response.text


def test_api_404_returns_json_not_html():
    response = client.get("/api/not-found-endpoint")
    assert response.status_code == 404
    assert "application/json" in response.headers["content-type"]


def test_static_files():
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
