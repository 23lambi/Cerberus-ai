"""PyInstaller entry point for the small, standalone launcher."""
import json
import os
import sys
from pathlib import Path

from launcher.manager import target_name
from launcher.ui import main

if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        Path(os.environ["CERBERUS_SMOKE_REPORT"]).write_text(json.dumps({"target": target_name(), "launcher": True}))
    else:
        main()
