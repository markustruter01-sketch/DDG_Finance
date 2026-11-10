"""Live versus research (finance-2027-plan.md Step 2 item 12). Read-only.

Once a day after the US close, each live sleeve's registered rules are run
twice for the same session: on the live feed (the account's own Alpaca daily
adjusted bars: SIP, or IEX when the account cannot read SIP) and on the
research vendor's bars (Yahoo adjusted closes, as research_harness/fetch.py
pulls them). Compared:
- FLEET-V1 (Atlas F1, Atlas V2 C1): votes, exposure E and target weights;
- MOMO-V2 (Momentum): book index, 100-session average, 20-session volatility,
  trend on/off, and each name's move since the selection day on both feeds
  (a bad split adjustment in one feed shows up here first);
- the live record: what the bot last decided (bots_state) and what the
  account holds now (bot_portfolio), as weights of the sleeve;
- feed: per symbol, the largest close gap between the vendors over the last
  20 shared sessions, and which Alpaca feed answered.
One row per account per day goes to live_research_check; monthly_summary()
reads a month. No orders, no bots_state writes.

Not covered: MOMO-V2's monthly selection from ~500 members is not re-run on
Yahoo (500 downloads a day); the check uses the live names list.
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sleeve_runtime import fleet_live, momo_live
from sleeve_runtime.trend_v1b import completed_bars

Bars = dict[str, list[dict[str, Any]]]

# Which sleeve owns which account. Change with the strategy cutover (plan item 18).
SLEEVES = {"oracle": fleet_live.F1, "jerome_macro": fleet_live.C1, "spy_qqq_trend": "MOMO-V2"}
FEED_SESSIONS = 20
# Flags: a gap this large is worth a look (not a pass bar).
FEED_GAP_FLAG = 0.005             # 0.5% on one close
WEIGHT_GAP_FLAG = 0.02            # 2 percentage points on one target weight
INDEX_GAP_FLAG = 0.01             # 1% on the MOMO-V2 book index or its average


# ── research vendor ───────────────────────────────────────────────────────────
def yahoo_fetcher(http_get: Callable | None = None, pause: float = 0.3):
    """BarFetcher on Yahoo's chart API, adjusted as research_harness/fetch.py does."""
    from research_harness.fetch import YAHOO_CHART, parse_yahoo_chart

    if http_get is None:
        import requests
        http_get = requests.get

    def fetch(symbols: list[str], start: date) -> Bars:
        end = date.today() + timedelta(days=1)
        p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
        p2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400
        out: Bars = {}
        for sym in symbols:
            try:
                resp = http_get(YAHOO_CHART.format(symbol=sym.replace(".", "-")),
                                params={"period1": p1, "period2": p2, "interval": "1d",
                                        "events": "div,splits", "includeAdjustedClose": "true"},
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
                resp.raise_for_status()
                out[sym] = [{"day": b["day"], "close": b["close"]}
                            for b in parse_yahoo_chart(resp.json(), start, end)]
            except Exception:
                out[sym] = []          # reported as missing, never filled
            time.sleep(pause)
        return out
    return fetch


# ── pure comparisons ──────────────────────────────────────────────────────────
def feed_gap(live: Bars, research: Bars, sessions: int = FEED_SESSIONS) -> dict[str, Any]:
    """Per symbol: the largest |live/research - 1| over the last ``sessions`` research days."""
    out: dict[str, Any] = {}
    for sym in sorted(set(live) | set(research)):
        r = {b["day"]: b["close"] for b in (research.get(sym) or [])}
        l = {b["day"]: b["close"] for b in (live.get(sym) or [])}
        days = sorted(r)[-sessions:]
        shared = [d for d in days if d in l and r[d] > 0]
        gaps = [(abs(l[d] / r[d] - 1), d) for d in shared]
        worst = max(gaps) if gaps else (None, None)
        out[sym] = {"max_gap": None if worst[0] is None else round(worst[0], 6),
                    "day": None if worst[1] is None else worst[1].isoformat(),
                    "shared": len(shared), "missing_live": len(days) - len(shared)}
    return out


def sleeve_weights(equity: Any, positions: list[dict[str, Any]] | None, *,
                   vault: set[str], cash_park: set[str]) -> dict[str, float] | None:
    """What the sleeve holds now, as weights of sleeve equity (vault out, parked cash = cash)."""
    try:
        eq = float(equity)
        vault_value = sum(float(p["value_usd"]) for p in positions or [] if p.get("symbol") in vault)
        sleeve = eq - vault_value
        if not math.isfinite(sleeve) or sleeve <= 0:
            return None
        return {p["symbol"]: round(float(p["value_usd"]) / sleeve, 6) for p in positions or []
                if p.get("symbol") not in vault | cash_park and float(p.get("value_usd") or 0)}
    except (TypeError, ValueError, KeyError):
        return None


def _max_gap(a: dict[str, float], b: dict[str, float]) -> float:
    return round(max((abs(a.get(s, 0.0) - b.get(s, 0.0)) for s in set(a) | set(b)), default=0.0), 6)


def fleet_compare(live: Bars, research: Bars, day: date, variant, mode: str,
                  state: dict[str, Any], held: dict[str, float] | None) -> dict[str, Any]:
    lt = fleet_live.targets_on(live, day, variant, mode)
    rt = fleet_live.targets_on(research, day, variant, mode)
    out: dict[str, Any] = {
        "kind": variant.registration, "day": day.isoformat(), "mode": mode,
        "live": None if lt is None else {"votes": lt["votes"], "exposure": round(lt["exposure"], 4),
                                         "weights": {k: round(v, 4) for k, v in lt["fleet"].items()}},
        "research": None if rt is None else {"votes": rt["votes"], "exposure": round(rt["exposure"], 4),
                                             "weights": {k: round(v, 4) for k, v in rt["fleet"].items()}},
    }
    if lt and rt:
        out["votes_agree"] = lt["votes"] == rt["votes"]
        out["exposure_gap"] = round(abs(lt["exposure"] - rt["exposure"]), 4)
        out["weight_gap"] = _max_gap(lt["fleet"], rt["fleet"])
    targets = state.get("targets") or {}
    out["last_decision"] = {k: state.get(k) for k in ("signal_day", "key", "votes", "exposure", "done")}
    if held is not None and targets:
        out["holdings_vs_last_targets"] = _max_gap(held, targets)
    return out


def momo_compare(live: Bars, research: Bars, day: date, state: dict[str, Any]) -> dict[str, Any]:
    names = state.get("names") or []
    sel = date.fromisoformat(state["selection_day"]) if state.get("selection_day") else None
    out: dict[str, Any] = {"kind": "MOMO-V2", "day": day.isoformat(), "names": len(names),
                           "selection_day": sel.isoformat() if sel else None,
                           "last_decision": {k: state.get(k) for k in
                                             ("signal_day", "key", "held", "trend_on", "index", "sma100", "vol20")}}
    if not names or sel is None:
        out["note"] = "no live names list yet"
        return out
    b = {}
    for label, bars in (("live", live), ("research", research)):
        x = momo_live.brakes(momo_live.book_index(bars, names, sel, day))
        b[label] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()}
    out.update(b)
    li, ri = b["live"], b["research"]
    if li.get("index") and ri.get("index"):
        out["index_gap"] = round(abs(li["index"] / ri["index"] - 1), 6)
    if li.get("sma100") and ri.get("sma100"):
        out["sma_gap"] = round(abs(li["sma100"] / ri["sma100"] - 1), 6)
    out["trend_agree"] = li.get("trend_on") == ri.get("trend_on")

    # Each name's close relative to its selection-day close, on both feeds, over
    # the sessions the brakes read: a split one vendor missed is a factor of 2+.
    window = momo_live.TREND_SESSIONS + momo_live.VOL_SESSIONS + 1
    gaps = []
    for n in names:
        lb = {x["day"]: x["close"] for x in live.get(n) or [] if x["day"] <= day}
        rb = {x["day"]: x["close"] for x in research.get(n) or [] if x["day"] <= day}
        if not lb.get(sel) or not rb.get(sel):
            continue
        shared = sorted(set(lb) & set(rb))[-window:]
        worst = max(((abs((lb[d] / lb[sel]) / (rb[d] / rb[sel]) - 1), d) for d in shared if rb[d] > 0),
                    default=None)
        if worst:
            gaps.append((round(worst[0], 4), n, worst[1].isoformat()))
    out["name_gaps"] = [{"symbol": n, "gap": g, "day": d} for g, n, d in sorted(gaps, reverse=True)[:5]]
    out["names_missing"] = len(names) - len(gaps)
    return out


def flags(row: dict[str, Any]) -> list[str]:
    """Plain-English reasons this row needs a look (empty = agrees)."""
    f = []
    if row.get("votes_agree") is False:
        f.append("votes differ between feeds")
    if (row.get("weight_gap") or 0) > WEIGHT_GAP_FLAG:
        f.append(f"target weight gap {row['weight_gap']:.1%}")
    if row.get("trend_agree") is False:
        f.append("MOMO trend on/off differs between feeds")
    for k in ("index_gap", "sma_gap"):
        if (row.get(k) or 0) > INDEX_GAP_FLAG:
            f.append(f"MOMO {k.split('_')[0]} gap {row[k]:.1%}")
    big = [g for g in row.get("name_gaps") or [] if g["gap"] > 0.05]
    if big:
        f.append("names moving differently by feed: " + ", ".join(f"{g['symbol']} {g['gap']:.0%}" for g in big))
    feed = [s for s, g in (row.get("feed") or {}).items() if (g.get("max_gap") or 0) > FEED_GAP_FLAG]
    if feed:
        f.append("close gap > 0.5%: " + ", ".join(sorted(feed)[:8]))
    # Missing data is never read as agreement.
    kind = str(row.get("kind") or "")
    if kind.startswith("FLEET") and not row.get("error"):
        f += [f"no signal from the {side} feed" for side in ("live", "research") if row.get(side) is None]
    if kind == "MOMO-V2" and not row.get("error") and not row.get("note"):
        f += [f"no book index from the {side} feed" for side in ("live", "research")
              if not (row.get(side) or {}).get("index")]
        if row.get("names_missing"):
            f.append(f"{row['names_missing']} names without prices on both feeds")
    if row.get("error"):
        f.append(row["error"])
    return f


# ── one day ───────────────────────────────────────────────────────────────────
def check_account(bot_id: str, *, live_fetch, research_fetch, state: dict[str, Any],
                  equity: Any, positions: list[dict[str, Any]] | None, now: datetime,
                  vault: set[str], cash_park: set[str]) -> dict[str, Any]:
    """One account, one session. Never raises: an error becomes the row."""
    sleeve = SLEEVES[bot_id]
    try:
        held = sleeve_weights(equity, positions, vault=vault, cash_park=cash_park)
        start = now.date() - timedelta(days=fleet_live.HISTORY_CALENDAR_DAYS)
        if sleeve == "MOMO-V2":
            symbols = sorted(set(state.get("names") or []) | {momo_live.SIGNAL})
        else:
            symbols = list(sleeve.symbols)
        live = completed_bars(live_fetch(symbols, start), now)
        research = completed_bars(research_fetch(symbols, start), now)
        spy = live.get("SPY") or []
        if not spy:
            raise RuntimeError("no live SPY bars")
        day = spy[-1]["day"]
        if sleeve == "MOMO-V2":
            row = momo_compare(live, research, day, state)
        else:
            mode = ((state.get("drawdown") or {}).get("mode")) or "normal"
            row = fleet_compare(live, research, day, sleeve, mode, state, held)
        row["feed"] = feed_gap(live, research) if sleeve != "MOMO-V2" else {
            s: g for s, g in feed_gap(live, research).items() if (g.get("max_gap") or 0) > FEED_GAP_FLAG}
        row["alpaca_feed"] = getattr(live_fetch, "last_feed", None)
        row["holdings"] = held
    except Exception as exc:
        row = {"kind": str(getattr(sleeve, "registration", sleeve)), "day": now.date().isoformat(),
               "error": f"check failed: {type(exc).__name__}: {exc}"[:300]}
    row["flags"] = flags(row)
    return row


# ── a month ───────────────────────────────────────────────────────────────────
def monthly_summary(rows: list[dict[str, Any]], month: str) -> dict[str, Any]:
    """rows: {bot_id, day, payload} for the month. Pure."""
    by_bot: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_bot.setdefault(r["bot_id"], []).append(r["payload"])
    out: dict[str, Any] = {"month": month, "bots": {}}
    for bot_id, days in sorted(by_bot.items()):
        flagged = [d for d in days if d.get("flags")]
        out["bots"][bot_id] = {
            "kind": days[-1].get("kind"), "days": len(days), "days_flagged": len(flagged),
            "votes_disagree": sum(1 for d in days if d.get("votes_agree") is False),
            "trend_disagree": sum(1 for d in days if d.get("trend_agree") is False),
            "max_weight_gap": max((d.get("weight_gap") or 0 for d in days), default=0),
            "max_index_gap": max((d.get("index_gap") or 0 for d in days), default=0),
            "alpaca_feeds": sorted({d.get("alpaca_feed") for d in days if d.get("alpaca_feed")}),
            "flags": sorted({f for d in flagged for f in d["flags"]})[:12],
        }
    return out


def summary_lines(summary: dict[str, Any]) -> list[str]:
    lines = []
    for bot_id, s in summary["bots"].items():
        verdict = "agrees" if not s["days_flagged"] else f"{s['days_flagged']}/{s['days']} days flagged"
        days = f"{s['days']} day{'s' if s['days'] != 1 else ''}"
        lines.append(f"{bot_id} ({s['kind']}): {days}, {verdict}; Alpaca feed {', '.join(s['alpaca_feeds']) or 'unknown'}")
        lines += [f"  - {f}" for f in s["flags"]]
    return lines or ["No checks recorded this month."]
