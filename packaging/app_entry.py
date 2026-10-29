"""PyInstaller entry point and isolated packaged-resource smoke check."""
import json
import os
import sys
from pathlib import Path

if "--check-release" in sys.argv:
    # The in-app updater's connection to GitHub, before any window code loads.
    from launcher.manager import check_release
    sys.exit(check_release())

if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
    os.environ["QT_API"] = "pyside6"

from desktop import main

if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        from main import app
        from cerberus.core.config import DATA_DIR, STATIC_DIR
        assert (STATIC_DIR / "index.html").is_file()
        assert (STATIC_DIR / "app.js").is_file()
        assert (STATIC_DIR / "cerberus.svg").is_file()
        assert DATA_DIR == Path(os.environ["CERBERUS_DATA"])
        # Exercise the bundled server too: Uvicorn loads several modules dynamically.
        import socket
        import urllib.request
        import desktop
        from cerberus.engines import engine
        engine.managed_binary = lambda: None
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            desktop.PORT = probe.getsockname()[1]
        server, thread = desktop.start_server()
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(desktop.address(), timeout=5) as response:
                assert b"Cerberus" in response.read()
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive()
        Path(os.environ["CERBERUS_SMOKE_REPORT"]).write_text(json.dumps({"static": True, "routes": len(app.routes)}))
    else:
        main()
