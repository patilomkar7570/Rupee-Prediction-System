"""Single source of truth for the app version."""
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
try:
    VERSION = VERSION_FILE.read_text(encoding="utf-8").strip()
except OSError:
    VERSION = "4.1.0-rc1"

if not VERSION or any(ch.isspace() for ch in VERSION):
    raise RuntimeError("VERSION must contain one non-empty version token.")
