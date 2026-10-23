"""Order client for the OANDA PRACTICE account (Forex Phase 5).

The only component that can change the Forex account. Practice host only
(hard-coded), market orders with the stop attached at entry, and closing a
whole trade. No other order types, no stop loosening, no transfers. Errors
are sanitised like OandaClient so the token can never reach a log.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

from core.oanda_client import BASE_URL, REQUEST_TIMEOUT_SECONDS, OandaClientError, OandaConfigurationError

assert BASE_URL == "https://api-fxpractice.oanda.com/v3", "Forex orders are practice-only"


def _reason(payload: dict[str, Any], status: int) -> str:
    """Why OANDA did not fill: a cancel's reason, a reject's rejectReason, or the error code."""
    cancel = payload.get("orderCancelTransaction") or payload.get("orderRejectTransaction") or {}
    reason = cancel.get("reason") or cancel.get("rejectReason") or payload.get("errorCode") or f"HTTP {status}"
    return str(reason)[:80]


class OandaTrader:
    def __init__(self, *, http_client: httpx.Client | None = None) -> None:
        token = os.environ.get("OANDA_API_TOKEN", "").strip()
        account_id = os.environ.get("OANDA_ACCOUNT_ID", "").strip()
        if not token or not account_id:
            raise OandaConfigurationError("Missing OANDA_API_TOKEN or OANDA_ACCOUNT_ID")
        self._token, self._account_id = token, account_id
        self._owns = http_client is None
        self._http = http_client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False)

    def close(self) -> None:
        if self._owns:
            self._http.close()

    def __enter__(self) -> "OandaTrader":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _send(self, method: str, resource: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        url = f"{BASE_URL}/accounts/{quote(self._account_id, safe='')}/{resource}"
        try:
            response = self._http.request(method, url, json=body, headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            })
            status = response.status_code
        except Exception:
            raise OandaClientError(f"OANDA practice {method} request failed") from None
        try:
            payload = response.json()
        except Exception:
            payload = {}
        return status, payload if isinstance(payload, dict) else {}

    def market_order(self, instrument: str, units: int, stop_price: str) -> dict[str, Any]:
        """Fill-or-kill market order that opens (never reduces) a position, with
        a GTC stop-loss attached on fill. Returns {"filled", "trade_id",
        "price", "units", "reason"}."""
        if not isinstance(units, int) or units == 0:
            raise ValueError("units must be a non-zero integer")
        status, payload = self._send("POST", "orders", {"order": {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "OPEN_ONLY",
            "stopLossOnFill": {"price": stop_price, "timeInForce": "GTC"},
        }})
        fill = payload.get("orderFillTransaction") or {}
        opened = fill.get("tradeOpened") or {}
        if status == 201 and opened.get("tradeID"):
            return {"filled": True, "trade_id": str(opened["tradeID"]),
                    "price": fill.get("price") or opened.get("price"),
                    "units": opened.get("units"), "reason": None}
        return {"filled": False, "trade_id": None, "price": None, "units": None, "reason": _reason(payload, status)}

    def close_trade(self, trade_id: str) -> dict[str, Any]:
        """Close the whole trade at market. Returns {"closed", "already_closed",
        "price", "pl", "reason"}."""
        status, payload = self._send("PUT", f"trades/{quote(str(trade_id), safe='')}/close", {"units": "ALL"})
        fill = payload.get("orderFillTransaction") or {}
        if status == 200 and fill:
            return {"closed": True, "already_closed": False, "price": fill.get("price"),
                    "pl": fill.get("pl"), "reason": None}
        if status == 404:
            return {"closed": False, "already_closed": True, "price": None, "pl": None,
                    "reason": "trade not open at OANDA"}
        return {"closed": False, "already_closed": False, "price": None, "pl": None, "reason": _reason(payload, status)}
