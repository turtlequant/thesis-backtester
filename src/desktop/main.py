"""
Desktop application entry point.

Starts FastAPI server in a background thread and opens a pywebview window.

Usage:
    python -m desktop.main
    # or from project root:
    python src/desktop/main.py
"""
import logging
import sys
import threading
import time
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Server configuration
HOST = "127.0.0.1"
PORT = 18721  # Arbitrary port for local use


def start_server():
    """Start the FastAPI server in the current thread."""
    import uvicorn
    from src.desktop.api.main import app

    uvicorn.run(
        app,
        host=HOST,
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
    logger.info("Starting desktop application...")

    # Start server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    if not wait_for_server():
        logger.error("Server failed to start within timeout")
        sys.exit(1)

    url = f"http://{HOST}:{PORT}"
    logger.info(f"Server ready at {url}")

    # Try to use pywebview for native window
    try:
        import webview

        window = webview.create_window(
            title="投研分析工具",
            url=url,
            width=1200,
            height=800,
            min_size=(900, 600),
            resizable=True,
        )
        webview.start()

    except ImportError:
        logger.warning(
            "pywebview not installed. Opening in browser instead.\n"
            "Install with: pip install pywebview"
        )
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
