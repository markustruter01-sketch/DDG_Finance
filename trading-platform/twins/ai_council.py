"""AI twins (TWINS-V2 Phase B, audit AU6; Markus said yes 20 Nov 2026 12:34 Brisbane).

No orders, ever: the AI only writes pretend-account decisions, replayed by the
same engine and costs as every other twin.

Two kinds of AI twin:
- "ai" twins of Atlas, Atlas V2 and Momentum (docs/plans/ai-twins-2027-registration.md):
  the three Forex council members each propose target weights from the bot's
  own asset list (Momentum: up to 50 names from its top-150 momentum list),
  within the bot's no-borrowing limit. 3 valid replies = their average,
  2 = the average of two, fewer = a missed vote (hold).
- "ai_veto" twins of three league lines (T-15X, S-MOMO-CAP, D-XTREND): the AI
  sees the line's rule weights and may only keep between 0% and 100% of each
  holding (reduce or skip, never add). The rest goes to T-bills.

One vote per US session, after the close (the nightly twins job, 17:15 New
York), filled at the next session's open by the engine. Every model call is
kept in twin_votes with its prompt, inputs, reply, tokens and cost.

Cost: tokens x the list prices below, charged to the AI twin's balance
monthly (the month's total is taken off from the first valued day of the next
month). INFERRED: Gemini's hidden "thinking" tokens may not all be in the token
count the council code returns, so its cost can be understated.
Cap: when this month's AI-twin cost reaches MONTHLY_CAP_USD, votes become
"missed" (never silently skipped).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from loguru import logger

from research_harness.harness.portfolio import HistoryView
from research_harness.league import base, families
from research_harness.sleeves import core_v1, xasset_v1
from twins import config, engine, store
from twins.config import DAILY, VERSION

AI_BOT = "league_ai"                 # bot_id of the league veto twins (kept off the league board)
VOTE_VERSION = 1                     # prompt and reply format; a change = a new dated version
MONTHLY_CAP_USD = 10.0               # PROPOSED (Opus 20 Nov): all AI twins together, per calendar month
MOMO_LIST = 150
MOMO_PICK = 50
MIN_VALID = 2

# USD per million tokens (input, output). Sources (checked 20 Nov 2026):
# Groq gpt-oss-120b 0.15 / 0.60 (third-party trackers citing GroqCloud docs; Groq's
# own launch post said 0.75 output); OpenRouter Nemotron ":free" 0 / 0;
# Gemini 3 Flash preview 0.50 / 3.00 (Google list price; a free tier, if this key
# is on one, would make it 0: UNKNOWN).
PRICES = {"openai/gpt-oss-120b": (0.15, 0.60),
          "nvidia/nemotron-3-ultra-550b-a55b:free": (0.0, 0.0),
          "gemini-3-flash-preview": (0.50, 3.00)}


@dataclass(frozen=True)
class AiTwin:
    twin_id: str
    bot_id: str
    kind: str                    # "ai" or "ai_veto"
    base: str                    # bot id, or the league line id
    max_gross: float
    stop_pct: float | None
    symbols: tuple[str, ...] = ()        # fixed list; empty = Momentum's top-150


ATLAS_CORE = ("SPY", "QQQ", "SSO", "QLD")
VETO_LINES = ("T-15X", "S-MOMO-CAP", "D-XTREND")


def twins() -> list[AiTwin]:
    out = [AiTwin(f"oracle:ai:v{VERSION}", "oracle", "ai", "oracle", 1.0, core_v1.STOP_PCT,
                  ATLAS_CORE + tuple(xasset_v1.LINES)),
           AiTwin(f"jerome_macro:ai:v{VERSION}", "jerome_macro", "ai", "jerome_macro", 1.0, core_v1.STOP_PCT,
                  ATLAS_CORE),
           AiTwin(f"spy_qqq_trend:ai:v{VERSION}", "spy_qqq_trend", "ai", "spy_qqq_trend", 1.0, 0.20)]
    from twins.league import LEAGUE_VERSION
    for line in VETO_LINES:
        s = families.BY_ID[line]
        out.append(AiTwin(f"{AI_BOT}:{line}:v{LEAGUE_VERSION}", AI_BOT, "ai_veto", line, s.max_gross, s.stop_pct))
    return out


# ── the pack: plain numbers only ─────────────────────────────────────────────
def _row(view: HistoryView, sym: str) -> dict[str, Any] | None:
    c = base.closes(view, sym, 253)
    if len(c) < 253:
        return None
    ret = lambda n: round(100 * (c[-1] / c[-1 - n] - 1), 2)
    vol = base.ann_vol(c, 20)
    return {"symbol": sym, "ret_20d_pct": ret(20), "ret_63d_pct": ret(63), "ret_252d_pct": ret(252),
            "vol_20d_pct": None if vol is None else round(100 * vol, 1),
            "above_200d_avg": c[-1] > sum(c[-200:]) / 200}


def momo_list(view: HistoryView, symbols: list[str]) -> list[str]:
    return families.rank_momentum(view, tuple(symbols), MOMO_LIST)


SYSTEM = (
    "You manage a pretend US share portfolio for a research test. No real money. "
    "Reply with one JSON object only, no other text. Use only the symbols given. "
    "Weights are fractions of the portfolio, each 0 or more. Whatever you do not invest sits in T-bills.")


def prompt(tw: AiTwin, day: date, rows: list[dict[str, Any]], held: dict[str, float],
           rule: dict[str, float] | None = None) -> str:
    if tw.kind == "ai_veto":
        ask = ("A fixed rule wants the holdings in 'rule_weight'. For each one you may keep a fraction between 0 "
               "(skip it) and 1 (keep all). You cannot add or increase anything. "
               'Reply: {"keep": {"SYMBOL": 0.0-1.0, ...}, "why": "one short sentence"}')
        rows = [dict(r, rule_weight=round(rule.get(r["symbol"], 0.0), 4)) for r in rows]
    else:
        pick = f"Pick at most {MOMO_PICK} symbols. " if not tw.symbols else ""
        ask = (f"Choose target weights for tomorrow's open. {pick}All weights together at most {tw.max_gross}. "
               "SSO and QLD are 2x funds. A 20% stop protects every holding. "
               'Reply: {"weights": {"SYMBOL": weight, ...}, "why": "one short sentence"}')
    data = {"date": day.isoformat(), "current_weights": {k: round(v, 4) for k, v in sorted(held.items())},
            "assets": rows}
    return ask + "\n" + json.dumps(data, separators=(",", ":"))


# ── replies ──────────────────────────────────────────────────────────────────
def parse(raw: str, tw: AiTwin, allowed: set[str], rule: dict[str, float] | None = None) -> dict[str, float]:
    """Target weights from one reply; ValueError if it breaks any rule (= no reply)."""
    start, end = raw.find("{"), raw.rfind("}")
    obj = json.loads(raw[start:end + 1]) if start >= 0 < end else None
    if not isinstance(obj, dict):
        raise ValueError("no JSON object")
    key = "keep" if tw.kind == "ai_veto" else "weights"
    got = obj.get(key)
    if not isinstance(got, dict):
        raise ValueError(f"no '{key}' object")
    out: dict[str, float] = {}
    for sym, v in got.items():
        if sym not in allowed:
            raise ValueError(f"{sym} is not on the list")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0:
            raise ValueError(f"{sym}: bad number")
        out[sym] = float(v)
    if tw.kind == "ai_veto":
        if any(v > 1 for v in out.values()):
            raise ValueError("keep above 1")
        return {s: w * out.get(s, 1.0) for s, w in (rule or {}).items() if s != base.CASH}
    out = {s: v for s, v in out.items() if v > 1e-9}
    if not tw.symbols and len(out) > MOMO_PICK:
        raise ValueError(f"{len(out)} names, more than {MOMO_PICK}")
    if sum(out.values()) > tw.max_gross + 1e-9:
        raise ValueError(f"weights add to {sum(out.values()):.4f}, above {tw.max_gross}")
    return out


def combine(replies: list[dict[str, float]]) -> dict[str, float] | None:
    if len(replies) < MIN_VALID:
        return None
    names = {s for r in replies for s in r}
    return {s: sum(r.get(s, 0.0) for r in replies) / len(replies) for s in sorted(names)}


def cost_usd(model: str, usage: dict[str, Any] | None) -> float | None:
    if model not in PRICES or not usage or usage.get("in") is None or usage.get("out") is None:
        return None
    p_in, p_out = PRICES[model]
    return round((usage["in"] * p_in + usage["out"] * p_out) / 1e6, 6)


# ── one night ────────────────────────────────────────────────────────────────
def _default_call(role: str, system: str, user: str) -> dict[str, Any]:
    from forex_council import call_model          # kraken-bot/forex_council.py: model calls only, no orders
    return call_model(role, system, user)


def _roles() -> tuple[str, ...]:
    from forex_council import VOTERS
    return VOTERS


def run(get_conn, now: datetime, session: date, bars: dict[str, list[dict[str, Any]]], *,
        call: Callable[[str, str, str], dict[str, Any]] | None = None, roles: tuple[str, ...] | None = None,
        start_equity: Callable[[str], float | None] | None = None) -> dict[str, Any]:
    """Tonight's vote for every AI twin. Creates a twin the first night it can."""
    call = call or _default_call
    roles = roles or _roles()
    report: dict[str, Any] = {}
    step_at = engine.step_close(session, DAILY)
    have = {a["twin_id"]: a for a in store.accounts(get_conn)}
    view = HistoryView(bars)
    view.today = session
    spent = store.ai_cost_since(get_conn, session.replace(day=1), [t.twin_id for t in twins()])
    for tw in twins():
        try:
            report[tw.twin_id] = _one(get_conn, now, session, step_at, tw, have, view, bars, call, roles,
                                      start_equity, spent)
            if isinstance(report[tw.twin_id], dict):
                spent += report[tw.twin_id].get("cost_usd", 0.0)
        except Exception as exc:
            logger.exception(f"ai twin {tw.twin_id} failed")
            report[tw.twin_id] = f"failed: {type(exc).__name__}"
    return report


def _one(get_conn, now, session, step_at, tw, have, view, bars, call, roles, start_equity, spent):
    from twins.job import _decide, _missed
    if tw.twin_id not in have:
        eq = 100_000.0 if tw.kind == "ai_veto" else (start_equity(tw.bot_id) if start_equity else None)
        if not eq:
            return "not started: the bot's balance is unknown tonight"
        store.create_account(get_conn, twin_id=tw.twin_id, bot_id=tw.bot_id, kind=tw.kind, version=VERSION,
                             bars=DAILY, start_at=step_at, start_equity=round(eq, 2),
                             config={"registration": "TWINS-V2", "base": tw.base, "vote_version": VOTE_VERSION,
                                     "max_gross": tw.max_gross, "allow_short": False, "stop_pct": tw.stop_pct,
                                     "models": {r: m for r, m in _models().items()},
                                     "costs": "twins.config.SHARE_COSTS; AI cost charged monthly"})
        store.log_change(get_conn, kind="twin_start", bot_id=tw.bot_id, source="twins:ai",
                         summary=f"AI twin {tw.twin_id} started with {eq:,.2f}", detail={"twin_id": tw.twin_id})
        return "started: votes from the next session"
    if any(engine.step_of(d["step_at"], DAILY) == session for d in store.decisions(get_conn, tw.twin_id)):
        return "already voted for this session"
    if spent >= MONTHLY_CAP_USD:
        _missed(get_conn, tw.twin_id, now, step_at, f"AI monthly cost cap {MONTHLY_CAP_USD} USD reached")
        return "missed: cost cap"

    rule = None
    if tw.kind == "ai_veto":
        from twins.league import LEAGUE_VERSION
        live = [d for d in store.decisions(get_conn, f"league:{tw.base}:v{LEAGUE_VERSION}") if not d["missed"]]
        if not live:
            _missed(get_conn, tw.twin_id, now, step_at, f"{tw.base} has no rule weights yet")
            return "missed: no rule weights"
        rule = live[-1]["weights"]
        symbols = [s for s in rule if s != base.CASH]
    elif tw.symbols:
        symbols = list(tw.symbols)
    else:
        skip = set(families.fixed_symbols())
        symbols = momo_list(view, [s for s in bars if s not in skip and "_" not in s])
    rows = [r for s in symbols if (r := _row(view, s))]
    if tw.kind == "ai_veto" and not symbols:         # the rule holds only T-bills: nothing to keep or skip
        _decide(get_conn, tw.twin_id, now, step_at, rule, reason="rule in T-bills; nothing to vote on")
        return "rule in cash"
    if len(rows) < max(1, len(symbols) // 2):
        _missed(get_conn, tw.twin_id, now, step_at, "price history unavailable for the asset list")
        return "missed: no price history"
    allowed = {r["symbol"] for r in rows}
    last = [d for d in store.decisions(get_conn, tw.twin_id) if not d["missed"]]
    held = {k: v for k, v in (last[-1]["weights"] if last else {}).items() if k != base.CASH}
    user = prompt(tw, session, rows, held, rule)

    calls, valid, total = [], [], 0.0
    for role in roles:
        t0 = time.monotonic()
        try:
            res = call(role, SYSTEM, user)
            raw, err = res["raw"], None
        except Exception as exc:
            res, raw, err = {"model": _models().get(role, "?"), "usage": None}, None, f"{type(exc).__name__}"
        c = cost_usd(res.get("model", ""), res.get("usage"))
        total += c or 0.0
        weights = None
        if raw is not None:
            try:
                weights = parse(raw, tw, allowed, rule)
                valid.append(weights)
            except (ValueError, json.JSONDecodeError) as exc:
                err = f"invalid reply: {exc}"[:200]
        calls.append({"role": role, "model": res.get("model", "?"), "raw": raw, "error": err, "cost": c,
                      "ms": int(1000 * (time.monotonic() - t0)), "weights": weights})

    target = combine(valid)
    inputs = {"vote_version": VOTE_VERSION, "valid": len(valid), "of": len(roles),
              "errors": [c["error"] for c in calls if c["error"]]}
    if target is None:
        dec = store.append_decision(get_conn, twin_id=tw.twin_id, decided_at=now, step_at=step_at, weights=None,
                                    missed=True, reason=f"{len(valid)} valid replies of {len(roles)}")
    else:
        target = base.with_cash(target) if tw.max_gross <= 1 else base.checked(target, tw.max_gross)
        dec = store.append_decision(get_conn, twin_id=tw.twin_id, decided_at=now, step_at=step_at,
                                    weights=target, inputs=inputs, reason=f"{len(valid)} of {len(roles)} replies")
    for c in calls:
        store.append_vote(get_conn, twin_id=tw.twin_id, decision_id=dec["id"], role=c["role"],
                          model_requested=_models().get(c["role"], c["model"]), model_returned=c["model"],
                          prompt=SYSTEM + "\n" + user, inputs={"error": c["error"], "weights": c["weights"]},
                          reply=c["raw"], cost_usd=c["cost"], latency_ms=c["ms"])
    return {"valid": len(valid), "of": len(roles), "missed": target is None, "cost_usd": round(total, 6)}


def _models() -> dict[str, str]:
    try:
        from forex_council import PROVIDERS
        return {r: p["model"] for r, p in PROVIDERS.items()}
    except Exception:
        return {}


def charge(curve: list[tuple[Any, float, float]], monthly_cost: dict[date, float]) -> list[tuple[Any, float, float]]:
    """Each month's AI cost taken off from the first valued day of the next month on."""
    out, cum = [], 0.0
    charged: set[date] = set()
    for step, eq, gross in curve:
        month = date(step.year, step.month, 1)
        for m, cost in monthly_cost.items():
            if m < month and m not in charged:
                cum += cost
                charged.add(m)
        out.append((step, eq - cum, gross))
    return out
