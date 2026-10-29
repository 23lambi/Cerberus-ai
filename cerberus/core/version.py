"""The packaged release tag, or "dev" when run from source."""
from cerberus.core.config import PROJECT_DIR

_version_file = PROJECT_DIR / "release-version.txt"
VERSION = _version_file.read_text().strip() if _version_file.is_file() else "dev"
