"""PyInstaller entry point for the small, standalone launcher."""
import json
import os
import sys
from pathlib import Path

from launcher.manager import check_release, target_name

if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        Path(os.environ["CERBERUS_SMOKE_REPORT"]).write_text(json.dumps({"target": target_name(), "launcher": True}))
    elif "--check-release" in sys.argv:
        sys.exit(check_release())  # before Tk: the CI containers have no display
    else:
        from launcher.ui import main
        main()
