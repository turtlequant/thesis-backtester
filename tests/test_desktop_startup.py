from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd

from src.desktop.api.routers import analysis
from src.desktop import main as desktop_main
from src.version import DISPLAY_VERSION


FRONTEND_DIR = Path(__file__).parents[1] / "src" / "desktop" / "frontend"


def test_desktop_window_has_its_own_valid_icon():
    icon = desktop_main.APP_ICON

    assert icon.exists()
    assert icon.stat().st_size > 0
    assert icon.read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert desktop_main.APP_USER_MODEL_ID != "python"


def test_runtime_bundle_resources_and_imports_are_available():
    assert desktop_main.runtime_check() == []


def test_runtime_check_report_contains_paths_and_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_main, "PROJECT_ROOT", tmp_path)

    report_path = desktop_main.write_runtime_check_report(["missing dependency"])

    payload = report_path.read_text(encoding="utf-8")
    assert '"ok": false' in payload
    assert f'"version": "{DISPLAY_VERSION}"' in payload
    assert "missing dependency" in payload


def test_desktop_window_passes_icon_to_pywebview(monkeypatch):
    calls = {}

    class FakeThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    fake_webview = SimpleNamespace(
        create_window=lambda **kwargs: calls.setdefault("window", kwargs),
        start=lambda **kwargs: calls.setdefault("start", kwargs),
    )
    monkeypatch.setattr(desktop_main, "configure_windows_app_identity", lambda: None)
    monkeypatch.setattr(desktop_main.threading, "Thread", FakeThread)
    monkeypatch.setattr(desktop_main, "wait_for_server", lambda: True)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    desktop_main.main()

    assert calls["window"]["title"] == f"Thesis Backtester · {DISPLAY_VERSION}"
    assert calls["start"]["icon"] == str(desktop_main.APP_ICON)


def test_frontend_startup_assets_are_local_and_licensed():
    index = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    app_source = (FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")

    assert "unpkg.com" not in index
    assert "<title>Thesis Backtester</title>" in index
    assert "THESIS BACKTESTER" in app_source
    assert "结构化投研引擎" in app_source
    assert "仅供研究与回测，不构成任何投资建议" in app_source
    assert "networkSession.loading" in app_source
    assert "局域网访问" in app_source
    for relative_path in (
        "vendor/vue.global.prod.js",
        "vendor/marked.min.js",
        "vendor/LICENSE.vue.txt",
        "vendor/LICENSE.marked.md",
    ):
        asset = FRONTEND_DIR / relative_path
        assert asset.exists()
        assert asset.stat().st_size > 100


def test_historical_stock_search_reads_only_selected_provider(monkeypatch):
    calls = []

    def fake_load_one(category, sub, partition, provider=None):
        calls.append((category, sub, partition, provider))
        return pd.DataFrame(
            [
                {"ts_code": "600000.SH", "name": "浦发银行", "list_status": "L"},
                {"ts_code": "600001.SH", "name": "已退市", "list_status": "D"},
            ]
        )

    from src.data import storage

    monkeypatch.setattr(storage, "load_one", fake_load_one)

    result = analysis._load_stock_list("tushare")

    assert calls == [("basic", "", "stock_list", "tushare")]
    assert result == [{"code": "600000.SH", "name": "浦发银行"}]
