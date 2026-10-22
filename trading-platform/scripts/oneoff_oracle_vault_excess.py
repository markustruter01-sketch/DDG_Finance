"""One-off (22 Oct 2026, approved by Markus): sell the BIL/VOO that the vault
re-buy loop bought with oracle's trading cash (15-21 Oct, PR #28).

Excess = broker quantity - vault ledger quantity (per_bot_vault_holdings.qty,
read from production just before running and passed in). Only that excess is
sold; the vault's own recorded holdings stay.

Dry run by default; --execute places the orders. Refuses when:
- the US market is closed,
- any BIL/VOO order is still open on the account,
- the excess is negative or worth more than MAX_EXCESS_USD for a symbol.

    python trading-platform/scripts/oneoff_oracle_vault_excess.py \
        --bil-ledger 25.31 --voo-ledger 3.29 [--execute]
"""

from __future__ import annotations

import argparse
import json
import math
import os

BOT_ID = "oracle"
SYMBOLS = ("BIL", "VOO")
# Read 21 Oct: about $610 of each. Anything far above means the numbers are
# wrong (or the loop is still running); stop and look.
MAX_EXCESS_USD = 1_000.0
QTY_DECIMALS = 6           # round DOWN, so we never sell vault-owned shares


def plan_sells(broker_qty: dict[str, float], ledger_qty: dict[str, float],
               price: dict[str, float]) -> list[dict]:
    out = []
    for s in SYMBOLS:
        excess = broker_qty.get(s, 0.0) - ledger_qty[s]
        if excess < 0:
            raise ValueError(f"{s}: broker {broker_qty.get(s, 0.0)} is below the vault ledger {ledger_qty[s]}")
        qty = math.floor(excess * 10**QTY_DECIMALS) / 10**QTY_DECIMALS
        usd = qty * price[s]
        if usd > MAX_EXCESS_USD:
            raise ValueError(f"{s}: excess ${usd:,.2f} is above the ${MAX_EXCESS_USD:,.0f} limit")
        if qty > 0:
            out.append({"symbol": s, "qty": qty, "approx_usd": round(usd, 2)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bil-ledger", type=float, required=True)
    ap.add_argument("--voo-ledger", type=float, required=True)
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args(argv)

    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
    from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

    client = TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=True)
    if not client.get_clock().is_open:
        raise SystemExit("market closed: refusing")
    open_orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=list(SYMBOLS)))
    if open_orders:
        raise SystemExit(f"{len(open_orders)} open BIL/VOO order(s): refusing")
    pos = {p.symbol: p for p in client.get_all_positions() if p.symbol in SYMBOLS}
    broker = {s: float(pos[s].qty) for s in pos}
    price = {s: float(pos[s].current_price) for s in pos}
    sells = plan_sells(broker, {"BIL": a.bil_ledger, "VOO": a.voo_ledger}, price)
    report = {"broker_qty": broker, "ledger_qty": {"BIL": a.bil_ledger, "VOO": a.voo_ledger},
              "sells": sells, "execute": a.execute}
    if a.execute:
        for s in sells:
            o = client.submit_order(MarketOrderRequest(
                symbol=s["symbol"], qty=s["qty"], side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
                client_order_id=f"vault-excess-fix-{BOT_ID}-{s['symbol'].lower()}"))
            s["order_id"], s["status"] = str(o.id), str(getattr(o.status, "value", o.status))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
