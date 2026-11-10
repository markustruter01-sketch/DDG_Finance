"""What each bot holds, in plain groups, as a share of its own account equity.

Home page bot cards (finance-2027-plan.md Step 2 item 13b, Markus 10 Nov 2026):
"so the strategy can be read off the card". The one symbol -> group map for the
platform lives here; the dashboard keeps no second list.

Source: bot_portfolio, which the runner writes each cycle from one broker read
(equity and positions from the same moment). No broker calls here.
- Alpaca accounts: each group's market value / account equity. Uninvested cash
  plus the SGOV cash park is "Cash"; BIL + VOO is "Vault". Items sum to 100%.
  Negative cash (money borrowed on margin) shows as "Borrowed".
- Forex (OANDA): each open pair with direction and size (units at the average
  entry price, in USD) / NAV, plus gross exposure. OANDA's open positions carry
  no current price, so sizes are at entry price, not marked to market.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

from core.symbols import canonical_symbol, is_crypto_symbol

# symbol -> (group, gearing). Gearing 2 = a 2x daily fund ("S&P 500 2x").
# Symbols not listed are single shares (MOMO-V2's stocks): group "Stocks".
SYMBOL_GROUPS: dict[str, tuple[str, int]] = {
    "SPY": ("S&P 500", 1), "SSO": ("S&P 500", 2),
    "QQQ": ("Nasdaq", 1), "QLD": ("Nasdaq", 2),
    "IEF": ("Bonds", 1),
    "GLD": ("Gold", 1), "UGL": ("Gold", 2),
    "SLV": ("Silver", 1), "AGQ": ("Silver", 2),
    "DBC": ("Commodities", 1),
    "UUP": ("Dollar", 1),
    "SGOV": ("Cash", 1),
    "BIL": ("Vault", 1), "VOO": ("Vault", 1),
}


_KRAKEN_BOT = str(Path(__file__).resolve().parents[2] / "kraken-bot")
if _KRAKEN_BOT not in sys.path:
    sys.path.append(_KRAKEN_BOT)  # appended: trading-platform's own packages still win


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def group_label(symbol: Any) -> str:
    key = canonical_symbol(symbol)
    if is_crypto_symbol(key):
        return "Crypto"
    group, gear = SYMBOL_GROUPS.get(key, ("Stocks", 1))
    return f"{group} {gear}x" if gear > 1 else group


def _items(values: dict[str, float], equity: float) -> list[dict[str, Any]]:
    out = [{"label": k, "pct": round(v / equity * 100, 1)} for k, v in values.items()]
    out = [i for i in out if i["pct"] != 0]
    return sorted(out, key=lambda i: -abs(i["pct"]))


def alpaca_holdings(equity: Any, positions: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Pure: groups as % of equity for one Alpaca account; None when unreadable."""
    eq = _num(equity)
    if not eq or eq <= 0 or not isinstance(positions, list):
        return None
    values: dict[str, float] = {}
    for p in positions:
        value = _num(p.get("value_usd"))
        if value is None:
            return None  # one unreadable line would make every share wrong
        label = group_label(p.get("symbol"))
        values[label] = values.get(label, 0.0) + value
    residual = eq - sum(values.values())
    if residual >= 0:
        values["Cash"] = values.get("Cash", 0.0) + residual
    else:
        values["Borrowed"] = residual
    return {"items": _items(values, eq), "gross_pct": None}


def forex_holdings(nav: Any, positions: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Pure: open pairs with direction and size (% of NAV, at entry price) plus gross."""
    import forex_risk  # kraken-bot: the registered USD-notional rule, one source

    eq = _num(nav)
    if not eq or eq <= 0 or not isinstance(positions, list):
        return None
    values: dict[str, float] = {}
    for p in positions:
        pair = str(p.get("instrument") or "")
        for side in ("long", "short"):
            leg = p.get(side) or {}
            units, price = _num(leg.get("units")), _num(leg.get("averagePrice"))
            if not units:
                continue
            if price is None:
                return None
            label = f"{pair.replace('_', '/')} {side}"
            values[label] = abs(units) * forex_risk.usd_notional_per_unit(pair, price)
    items = _items(values, eq)
    return {"items": items, "gross_pct": round(sum(values.values()) / eq * 100, 1)}


def holdings_by_bot(portfolios: list[dict[str, Any]], bot_ids: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in portfolios:
        bot_id = p.get("bot_id")
        if bot_id not in bot_ids:
            continue
        fn = forex_holdings if bot_id == "forex_ai" else alpaca_holdings
        try:
            held = fn(p.get("equity_usd"), p.get("positions"))
        except Exception:
            held = None
        upd = p.get("last_updated")
        out[bot_id] = None if held is None else {
            **held, "as_of": upd if isinstance(upd, str) or upd is None else upd.isoformat(),
        }
    return out
