"""Central paths: tracked templates stay in the repository; generated/user data lives in runtime/."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "data"

# Set RPS_RUNTIME_DIR to keep mutable or private files outside the repository if desired.
_runtime_override = os.environ.get("RPS_RUNTIME_DIR", "").strip()
RUNTIME_DIR = Path(_runtime_override).expanduser().resolve() if _runtime_override else PROJECT_ROOT / "runtime"
INPUT_DIR = RUNTIME_DIR / "inputs"

MARKET_DATA_FILE = RUNTIME_DIR / "market_data.csv"
SOURCE_STATUS_FILE = RUNTIME_DIR / "source_status.json"
BACKTEST_RESULTS_FILE = RUNTIME_DIR / "backtest_results.json"
LATEST_DAILY_RUN_FILE = RUNTIME_DIR / "latest_daily_run.json"
MACRO_INPUT_FILE = INPUT_DIR / "macro_inputs.csv"
EVENT_INPUT_FILE = INPUT_DIR / "event_inputs.csv"
FACTOR_WEIGHTS_FILE = INPUT_DIR / "factor_weights.csv"
FACTOR_AUDIT_JSON = RUNTIME_DIR / "factor_audit.json"
FACTOR_AUDIT_CSV = RUNTIME_DIR / "factor_audit.csv"
SHADOW_FORECASTS_FILE = RUNTIME_DIR / "shadow_forecasts.csv"
OFFICIAL_REFERENCE_RATE_FILE = INPUT_DIR / "official_usdinr_reference.csv"
TARGET_SOURCE_CONFIG_FILE = INPUT_DIR / "target_source.json"


def ensure_runtime_layout() -> None:
    """Create local runtime folders and first-run copies of blank user-input templates."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    template_pairs = (
        (TEMPLATE_DIR / "macro_inputs_template.csv", MACRO_INPUT_FILE),
        (TEMPLATE_DIR / "event_inputs_template.csv", EVENT_INPUT_FILE),
        (TEMPLATE_DIR / "factor_weights_template.csv", FACTOR_WEIGHTS_FILE),
        (TEMPLATE_DIR / "official_usdinr_reference_template.csv", OFFICIAL_REFERENCE_RATE_FILE),
    )
    for source, destination in template_pairs:
        if source.exists() and not destination.exists():
            shutil.copyfile(source, destination)
    if not TARGET_SOURCE_CONFIG_FILE.exists():
        TARGET_SOURCE_CONFIG_FILE.write_text('{"target_source": "yahoo_proxy"}\n', encoding="utf-8")
