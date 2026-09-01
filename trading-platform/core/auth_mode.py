"""Trading API authentication mode configuration."""

from __future__ import annotations

import os


AUTH_MODE_ENV = "TRADING_API_AUTH_MODE"
AUTH_MODE_ENFORCED = "enforced"
AUTH_MODE_BYPASS = "bypass"


def get_trading_api_auth_mode() -> str:
    """Return the configured mode, failing closed for unset or invalid values."""
    configured_mode = os.getenv(AUTH_MODE_ENV, "").strip().lower()
    return (
        AUTH_MODE_BYPASS
        if configured_mode == AUTH_MODE_BYPASS
        else AUTH_MODE_ENFORCED
    )