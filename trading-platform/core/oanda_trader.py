"""Order client for the OANDA PRACTICE account (Forex Phase 5).

The only component that can change the Forex account. Practice host only
(hard-coded), market orders with the stop attached at entry, and closing a
whole trade. No other order types, no stop loosening, no transfers. Errors
are sanitised like OandaClient so the token can never reach a log.

Every order carries a client ID (order and trade). An answer that is neither
a clear fill nor a clear refusal (401, 5xx, time-out, lost connection) may
hide a fill, so the order is read back by its client ID before the answer is
given; it is never sent again (16 Nov 2026 order-path audit, F2).
"""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import httpx

from core.oanda_client import BASE_URL, REQUEST_TIMEOUT_SECONDS, OandaClientError, OandaConfigurationError
from core.order_ids import make_client_order_id

assert BASE_URL == "https://api-fxpractice.oanda.com/v3", "Forex orders are practice-only"

CLIENT_TAG = "forex_ai"
LOOKUP_TRIES = 3              # read-backs of an unclear order answer
LOOKUP_PAUSE_SECONDS = 2.0


def client_id_prefix(instrument: str) -> str:
    """Prefix of this system's client IDs for one pair (see order_ids)."""
    return f"fx-{instrument}"


def _reason(payload: dict[str, Any], status: int) -> str:
    """Why OANDA did not fill: a cancel's reason, a reject's rejectReason, or the error code."""
    cancel = payload.get("orderCancelTransaction") or payload.get("orderRejectTransaction") or {}
    reason = cancel.get("reason") or cancel.get("rejectReason") or payload.get("errorCode") or f"HTTP {status}"
    return str(reason)[:80]


def _result(client_id: str, filled: bool, *, trade_id: str | None = None, price: Any = None,
            units: Any = None, reason: str | None = None, unclear: bool = False) -> dict[str, Any]:
    return {"filled": filled, "trade_id": trade_id, "price": price, "units": units,
            "reason": reason, "client_id": client_id, "unclear": unclear}


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

    def _send(self, method: str, resource: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
        from core.link_health import record_link
        try:
            status, payload = self._send_unrecorded(method, resource, body)
        except OandaClientError as exc:
            record_link("OANDA practice", False, str(exc))
            raise
        if status in (401, 403):
            record_link("OANDA practice", False, f"OANDA practice {method} returned HTTP {status}")
        else:
            record_link("OANDA practice", True)
        return status, payload

    def _send_unrecorded(self, method: str, resource: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
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
        "price", "units", "reason", "client_id", "unclear"}. ``unclear`` is
        True only when the answer was unclear AND the read-back failed: the
        order may have filled."""
        if not isinstance(units, int) or units == 0:
            raise ValueError("units must be a non-zero integer")
        from core.no_crypto import refuse_crypto_units
        refuse_crypto_units(instrument, units, "OANDA market_order")  # no crypto, anywhere (17 Nov 2026)
        client_id = make_client_order_id(client_id_prefix(instrument))
        try:
            status, payload = self._send("POST", "orders", {"order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "OPEN_ONLY",
                "stopLossOnFill": {"price": stop_price, "timeInForce": "GTC"},
                "clientExtensions": {"id": client_id, "tag": CLIENT_TAG},
                "tradeClientExtensions": {"id": f"{client_id}-t", "tag": CLIENT_TAG},
            }})
        except OandaClientError as exc:
            return self._read_back(client_id, str(exc))
        fill = payload.get("orderFillTransaction") or {}
        opened = fill.get("tradeOpened") or {}
        if status == 201 and opened.get("tradeID"):
            return _result(client_id, True, trade_id=str(opened["tradeID"]),
                           price=fill.get("price") or opened.get("price"), units=opened.get("units"))
        if status in (201, 400):           # a clear cancel (FOK) or refusal: nothing was opened
            return _result(client_id, False, reason=_reason(payload, status))
        return self._read_back(client_id, f"HTTP {status}")

    def _read_back(self, client_id: str, why: str) -> dict[str, Any]:
        """The order answer was unclear: read the order by its client ID."""
        for attempt in range(LOOKUP_TRIES):
            if attempt:
                time.sleep(LOOKUP_PAUSE_SECONDS)
            try:
                status, payload = self._send("GET", f"orders/@{quote(client_id, safe='')}", None)
            except OandaClientError:
                continue
            if status == 404:
                return _result(client_id, False, reason=f"not placed (read back after {why})")
            order = payload.get("order") or {}
            state = str(order.get("state") or "").upper()
            if status == 200 and state == "FILLED" and order.get("tradeOpenedID"):
                return _result(client_id, True, trade_id=str(order["tradeOpenedID"]))
            if status == 200 and state == "CANCELLED":
                return _result(client_id, False, reason=f"cancelled (read back after {why})")
        return _result(client_id, False, unclear=True,
                       reason=f"unclear answer ({why}) and read-back failed: may have filled")

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
