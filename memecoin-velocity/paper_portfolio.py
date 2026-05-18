"""Paper portfolio for memecoin velocity."""
import json
import os
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(_HERE, "memecoin_paper_portfolio.json")
STARTING_EQUITY = 100_000.0


def _load():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    return {"cash_usd": STARTING_EQUITY, "positions": {}, "trade_history": []}


def _save(state):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def get_equity():
    s = _load()
    pos_value = sum(
        p["units"] * p.get("current_price", p["entry_price"])
        for p in s["positions"].values()
    )
    return s["cash_usd"] + pos_value


def get_cash():
    return _load()["cash_usd"]


def has_position(asset: str) -> bool:
    return asset in _load()["positions"]


def position_count() -> int:
    return len(_load()["positions"])


def open_position(asset, units, price, pair="", volume_ratio=0.0, reddit_mentions=0):
    s = _load()
    cost = units * price
    s["cash_usd"] -= cost
    s["positions"][asset] = {
        "units": units,
        "entry_price": price,
        "current_price": price,
        "peak_price": price,
        "pair": pair,
        "volume_ratio": volume_ratio,
        "reddit_mentions": reddit_mentions,
        "entry_time": datetime.utcnow().isoformat(),
    }
    _save(s)


def update_position_price(asset, current_price):
    s = _load()
    if asset in s["positions"]:
        s["positions"][asset]["current_price"] = current_price
        if current_price > s["positions"][asset].get("peak_price", 0):
            s["positions"][asset]["peak_price"] = current_price
        _save(s)


def close_position(asset, exit_price, reason):
    s = _load()
    if asset not in s["positions"]:
        return None
    p = s["positions"].pop(asset)
    proceeds = p["units"] * exit_price
    s["cash_usd"] += proceeds
    pnl = proceeds - (p["units"] * p["entry_price"])
    trade = {
        "asset": asset,
        "pair": p.get("pair", ""),
        "entry_price": p["entry_price"],
        "exit_price": exit_price,
        "units": p["units"],
        "pnl_usd": pnl,
        "reason": reason,
        "volume_ratio": p.get("volume_ratio", 0),
        "reddit_mentions": p.get("reddit_mentions", 0),
        "entry_time": p["entry_time"],
        "exit_time": datetime.utcnow().isoformat(),
    }
    s["trade_history"].append(trade)
    _save(s)
    return trade
