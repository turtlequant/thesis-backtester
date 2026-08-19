"""
Desktop application entry point.

Starts FastAPI server in a background thread and opens a pywebview window.

Usage:
    python -m src.desktop.main
    # Direct execution is also supported from the project root:
    python src/desktop/main.py
"""
import logging
import importlib
import json
import sys
import threading
import time
from pathlib import Path

# Direct source-file execution needs this bootstrap. Module and compiled modes
# already have the package import path.
SOURCE_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_PROJECT_ROOT))

from src.desktop import network_access  # noqa: E402
from src.version import DISPLAY_VERSION  # noqa: E402
from src.data.settings import (  # noqa: E402
    FACTORS_ROOT,
    OPERATORS_ROOT,
    PROJECT_ROOT,
    SCREENING_STRATEGIES_ROOT,
    STRATEGIES_ROOT,
    WORKSPACE_ROOT,
    prepare_workspace,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Server configuration
HOST = network_access.LOOPBACK_HOST
PORT = network_access.DEFAULT_PORT
APP_ICON = PROJECT_ROOT / "src" / "desktop" / "assets" / "icon.ico"
APP_USER_MODEL_ID = "thesis-backtester.desktop"

RUNTIME_ASSETS = (
    PROJECT_ROOT / "src" / "desktop" / "frontend" / "index.html",
    APP_ICON,
    PROJECT_ROOT / "src" / "data" / "catalog" / "native_fields.yaml",
    PROJECT_ROOT / "docs" / "PRODUCT_GUIDE.md",
    OPERATORS_ROOT / "v2" / "README.md",
    FACTORS_ROOT / "definitions",
    SCREENING_STRATEGIES_ROOT,
    STRATEGIES_ROOT / "v6_value" / "strategy.yaml",
)

RUNTIME_IMPORTS = (
    "fastapi",
    "uvicorn",
    "webview",
    "pandas",
    "polars",
    "openai",
    "akshare",
    "baostock",
    "tushare",
    "matplotlib",
)


def runtime_check() -> list[str]:
    """Return missing runtime resources/imports for source and packaged builds."""
    errors = []
    try:
        prepare_workspace()
    except Exception as exc:
        errors.append(f"无法准备研究工作区: {exc}")
    errors.extend(f"缺少运行时资源: {path}" for path in RUNTIME_ASSETS if not path.exists())
    for module_name in RUNTIME_IMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"无法导入 {module_name}: {exc}")
    if sys.platform == "win32":
        try:
            importlib.import_module("webview.platforms.winforms")
        except Exception as exc:
            errors.append(f"无法加载 pywebview WinForms 后端: {exc}")
    return errors


def write_runtime_check_report(errors: list[str]) -> Path:
    """Persist diagnostics because release builds intentionally hide the console."""
    report_path = PROJECT_ROOT / "runtime-check.json"
    payload = {
        "ok": not errors,
        "version": DISPLAY_VERSION,
        "project_root": str(PROJECT_ROOT),
        "workspace_root": str(WORKSPACE_ROOT),
        "executable": sys.executable,
        "errors": errors,
    }
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


def configure_windows_app_identity() -> None:
    """Give the desktop window its own Windows taskbar identity."""
    if sys.platform != "win32":
        return

    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID
        )
    except Exception:
        logger.debug("Unable to configure Windows application identity", exc_info=True)


def start_server(bind_host: str = HOST):
    """Start the FastAPI server in the current thread."""
    import uvicorn
    from src.desktop.api.main import app

    uvicorn.run(
        app,
        host=bind_host,
        port=PORT,
        log_level="warning",
        access_log=False,
    )


def wait_for_server(timeout: float = 15.0) -> bool:
    """Wait until the server is ready to accept connections."""
    import socket

    start = time.time()
    while time.time() - start < timeout:
        try:
            sock = socket.create_connection((HOST, PORT), timeout=1)
            sock.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)
    return False


def main():
    """Main entry point — start server + open webview window."""
    if "--runtime-check" in sys.argv:
        errors = runtime_check()
        write_runtime_check_report(errors)
        for message in errors:
            logger.error(message)
        raise SystemExit(1 if errors else 0)

    prepare_workspace()
    logger.info("Starting desktop application...")
    logger.info("Research workspace: %s", WORKSPACE_ROOT)
    configure_windows_app_identity()

    network_settings = network_access.load_network_settings()
    lan_access_enabled = network_settings["enabled"]
    network_access.configure_active_lan_access(lan_access_enabled)
    bind_host = (
        network_access.LAN_BIND_HOST if lan_access_enabled else network_access.LOOPBACK_HOST
    )

    # Start server in background thread
    server_thread = threading.Thread(target=start_server, args=(bind_host,), daemon=True)
    server_thread.start()

    # Wait for server to be ready
    if not wait_for_server():
        logger.error("Server failed to start within timeout")
        sys.exit(1)

    url = f"http://{HOST}:{PORT}"
    logger.info(f"Server ready at {url}")
    if lan_access_enabled:
        lan_urls = network_access.lan_access_urls(PORT)
        logger.info("LAN access enabled: %s", ", ".join(lan_urls) or "address unavailable")

    # Try to use pywebview for native window
    try:
        import webview

        webview.create_window(
            title=f"Thesis Backtester · {DISPLAY_VERSION}",
            url=url,
            width=1200,
            height=800,
            min_size=(900, 600),
            resizable=True,
        )
        icon_path = str(APP_ICON) if APP_ICON.is_file() else None
        webview.start(icon=icon_path)

    except Exception:
        logger.exception("Native desktop window unavailable. Opening in browser instead.")
        import webbrowser
        webbrowser.open(url)

        # Keep the server running
        print(f"\nServer running at {url}")
        print("Press Ctrl+C to stop.\n")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            print("\nShutting down...")


if __name__ == "__main__":
    main()
