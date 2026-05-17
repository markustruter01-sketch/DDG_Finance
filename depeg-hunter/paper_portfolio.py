"""Paper portfolio for depeg hunter — mirrors poseidon/paper_portfolio.py pattern."""
import json
import os
from datetime import datetime

PORTFOLIO_FILE   = "depeg-hunter/depeg_paper_portfolio.json"
STARTING_EQUITY  = 100_000.0


def _load() -> dict:
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    return {"cash_usd": STARTING_EQUITY, "positions": {}, "trade_history": []}


def _save(state: dict) -> None:
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def get_equity() -> float:
    s = _load()
    pos_value = sum(p["units"] * p["current_price"] for p in s["positions"].values())
    return s["cash_usd"] + pos_value


def get_cash() -> float:
    return _load()["cash_usd"]


def has_position(stable: str) -> bool:
    return stable in _load()["positions"]


def position_count() -> int:
    return len(_load()["positions"])


def open_position(stable: str, units: float, price: float, severity: str) -> None:
    s = _load()
    cost = units * price
    s["cash_usd"] -= cost
    s["positions"][stable] = {
        "units": units,
        "entry_price": price,
        "current_price": price,
        "severity": severity,
        "entry_time": datetime.utcnow().isoformat(),
    }
    _save(s)


def update_position_price(stable: str, current_price: float) -> None:
    s = _load()
    if stable in s["positions"]:
        s["positions"][stable]["current_price"] = current_price
        _save(s)


def close_position(stable: str, exit_price: float, reason: str) -> dict | None:
    s = _load()
    if stable not in s["positions"]:
        return None
    p = s["positions"].pop(stable)
    proceeds = p["units"] * exit_price
    s["cash_usd"] += proceeds
    pnl = proceeds - (p["units"] * p["entry_price"])
    trade = {
        "stable":      stable,
        "entry_price": p["entry_price"],
        "exit_price":  exit_price,
        "units":       p["units"],
        "pnl_usd":     pnl,
        "reason":      reason,
        "severity":    p["severity"],
        "entry_time":  p["entry_time"],
        "exit_time":   datetime.utcnow().isoformat(),
    }
    s["trade_history"].append(trade)
    _save(s)
    return trade
