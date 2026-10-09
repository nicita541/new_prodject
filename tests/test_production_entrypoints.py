"""Guard the real Windows startup against accidental demo regressions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_old_interface_shortcut_delegates_to_real_entrypoint():
    shortcut = (ROOT / "ПОСМОТРЕТЬ_ИНТЕРФЕЙС.bat").read_text(encoding="utf-8")
    assert 'call "%~dp0start.bat"' in shortcut
    assert ".venv" not in shortcut
    assert "8766" not in shortcut
    assert "create_studio_demo" not in shortcut


def test_production_entrypoint_uses_portable_runtime_and_real_build():
    launcher = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert r"tools\python\python.exe" in launcher
    assert r"frontend\dist\studio-edition.html" in launcher
    assert r"frontend\dist\studio-live-bridge.js" in launcher
    assert "npm.cmd run build" in launcher
    assert "http://127.0.0.1:8765" in launcher
    assert "create_studio_demo" not in launcher


def test_development_proxy_matches_actual_backend_port():
    vite_config = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    assert "process.env.KADR_STUDIO_API_PORT || '8765'" in vite_config


def test_no_synthetic_demo_is_shipped_as_startup_code():
    assert not (ROOT / "scripts" / "create_studio_demo.py").exists()
