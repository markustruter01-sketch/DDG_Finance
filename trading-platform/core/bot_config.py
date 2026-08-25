"""Load the kraken-bot configuration as the shared runtime source."""
from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_bot_profiles() -> dict[str, dict[str, Any]]:
    config_path = Path(__file__).resolve().parents[2] / "kraken-bot" / "config.py"
    spec = importlib.util.spec_from_file_location("_shared_kraken_bot_config", config_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load bot config from {config_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BOT_PROFILES