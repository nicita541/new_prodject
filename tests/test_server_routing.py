import pytest
import httpx
from fastapi.testclient import TestClient
from app.server import app

client = TestClient(app)

def test_react_routes_serve_index():
    # When hitting React app routes, it should return the frontend index.html
    routes = [
        "/",
        "/projects",
        "/trash",
        "/project/123",
        "/episode/test/edit",
        "/episode/test/review/job123"
    ]
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<div id=\"root\"></div>" in response.text, f"Route {route} did not serve React index"

def test_legacy_route_serves_legacy_index():
    response = client.get("/legacy")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "app.js" in response.text or "library.js" in response.text, "Legacy index not served"

def test_api_404_returns_json_not_html():
    response = client.get("/api/not-found-endpoint")
    assert response.status_code == 404
    assert "application/json" in response.headers["content-type"]

def test_static_files():
    # React assets
    # Legacy assets
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
