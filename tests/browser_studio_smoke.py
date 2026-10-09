"""Real Chromium smoke check: CSS/JS must EXECUTE under production CSP.

TestClient + jsdom don't enforce Content-Security-Policy. The previous CI was
green even as users saw an unstyled white page with dead navigation.
Run as `python tests/browser_studio_smoke.py` on a runner with Playwright.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app",
         "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        for attempt in range(100):
            if proc.poll() is not None:
                raise RuntimeError("Server exited before starting")
            try:
                with urlopen(base + "/api/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.15)
        else:
            raise TimeoutError("Studio server never became ready")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            problems = []
            page.on("pageerror", lambda error: problems.append(str(error)))
            page.on("console", lambda msg: problems.append(msg.text) if
                    msg.type == "error" and "Content Security Policy" in msg.text else None)
            response = page.goto(base + "/", wait_until="networkidle", timeout=30_000)
            assert response is not None and response.status == 200, f"HTTP {response.status if response else '?'}"
            page.locator(".sidebar").wait_for(state="visible", timeout=20_000)
            background = page.evaluate("getComputedStyle(document.body).backgroundColor")
            assert background == "rgb(9, 13, 21)", f"Missing Studio CSS! Browser rendered body={background}"
            display = page.locator(".sidebar").evaluate("(el) => getComputedStyle(el).display")
            assert display == "flex", f"Studio sidebar not styled, display={display}"
            assert page.evaluate("Boolean(window.KadrBridge)"), "Missing live API JavaScript bridge"
            assert page.locator(".navbtn").count() >= 7
            assert page.locator("main").inner_text().strip(), "Studio application did not render projects"
            page.locator('button[data-action="nav"][data-screen="trash"]').click()
            assert "Корзина" in page.locator("main").inner_text()
            assert not problems, "Browser CSP or JS errors:\n" + "\n".join(problems)
            print("CHROMIUM PASS: dark theme, CSS computed styles, real JS, projects, navigation, strict CSP")
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=10)


if __name__ == "__main__":
    main()
