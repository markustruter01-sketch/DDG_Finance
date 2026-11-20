"""AI twins (AU6): replies checked, votes combined and kept, cost charged and capped. No network."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import pytest

import twins  # noqa: F401
from twins import ai_council as ai
from twins import store
from twins.engine import NEW_YORK
from twins_pg import make_get_conn, needs_pg

ATLAS = next(t for t in ai.twins() if t.bot_id == "oracle")
MOMO = next(t for t in ai.twins() if t.bot_id == "spy_qqq_trend")
VETO = next(t for t in ai.twins() if t.base == "T-15X")


def test_weights_reply_rules():
    allowed = {"SPY", "QQQ", "SSO"}
    assert ai.parse('ok {"weights": {"SPY": 0.5, "QQQ": 0.3}, "why": "x"}', ATLAS, allowed) == {"SPY": 0.5, "QQQ": 0.3}
    for bad in ('{"weights": {"TSLA": 0.1}}', '{"weights": {"SPY": 0.8, "QQQ": 0.3}}',
                '{"weights": {"SPY": -0.1}}', '{"weights": {"SPY": true}}', '{"keep": {}}', "no json"):
        with pytest.raises(ValueError):
            ai.parse(bad, ATLAS, allowed)
    names = {f"N{i}" for i in range(60)}
    with pytest.raises(ValueError, match="more than 50"):
        ai.parse(json.dumps({"weights": {n: 0.01 for n in names}}), MOMO, names)


def test_veto_can_only_reduce():
    rule = {"SSO": 0.6, "QLD": 0.4, "BIL": 0.0}
    got = ai.parse('{"keep": {"SSO": 0.5, "QLD": 0}}', VETO, {"SSO", "QLD"}, rule)
    assert got == {"SSO": 0.3, "QLD": 0.0}
    assert ai.parse('{"keep": {}}', VETO, {"SSO", "QLD"}, rule) == {"SSO": 0.6, "QLD": 0.4}   # silent = keep
    with pytest.raises(ValueError, match="above 1"):
        ai.parse('{"keep": {"SSO": 1.2}}', VETO, {"SSO", "QLD"}, rule)


def test_combine_needs_two_and_averages():
    assert ai.combine([{"SPY": 0.6}]) is None
    assert ai.combine([{"SPY": 0.6}, {"SPY": 0.2, "QQQ": 0.4}, {"QQQ": 0.2}]) == pytest.approx(
        {"QQQ": 0.2, "SPY": 0.8 / 3})


def test_cost_and_monthly_charge():
    assert ai.cost_usd("openai/gpt-oss-120b", {"in": 2_000_000, "out": 1_000_000}) == pytest.approx(0.9)
    assert ai.cost_usd("unknown-model", {"in": 1, "out": 1}) is None
    curve = [(date(2026, 11, 27), 100.0, 0), (date(2026, 11, 30), 100.0, 0), (date(2026, 12, 1), 100.0, 0),
             (date(2027, 1, 4), 100.0, 0)]
    out = ai.charge(curve, {date(2026, 11, 1): 2.5, date(2026, 12, 1): 1.0})
    assert [p[1] for p in out] == [100.0, 100.0, 97.5, 96.5]


# ── one night against a throwaway Postgres ───────────────────────────────────
def _bars(days):
    out = {}
    syms = list(ai.ATLAS_CORE) + ["IEF", "GLD", "DBC", "UUP", "BIL", "SPY"] + [f"M{i:03d}" for i in range(160)]
    for k, s in enumerate(dict.fromkeys(syms)):
        px, rows = 50.0 + k, []
        for i, d in enumerate(days):
            px *= 1 + (0.0005 + k * 1e-6) * (1 if i % 3 else -0.5)
            rows.append({"day": d, "open": px, "high": px, "low": px, "close": px})
        out[s] = rows
    return out


def _days(n, end):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


@needs_pg
def test_two_nights_start_then_vote_keep_every_call_and_respect_the_cap():
    get_conn = make_get_conn()
    store.ensure_schema(get_conn)
    days = _days(300, date(2026, 11, 24))
    bars = _bars(days)
    calls = []

    def fake(role, system, user):
        calls.append(role)
        data = json.loads(user.split("\n", 1)[1])
        syms = [r["symbol"] for r in data["assets"]]
        if role == "member_3":
            return {"model": "gemini-3-flash-preview", "raw": "not json", "usage": {"in": 1000, "out": 500}}
        if "keep" in user.split("\n", 1)[0]:
            return {"model": "openai/gpt-oss-120b", "raw": json.dumps({"keep": {s: 0.5 for s in syms}}),
                    "usage": {"in": 1000, "out": 500}}
        w = {s: 0.9 / min(len(syms), 10) for s in syms[:10]}
        return {"model": "openai/gpt-oss-120b", "raw": json.dumps({"weights": w}), "usage": {"in": 1000, "out": 500}}

    # The league line the veto twins follow, with a rule decision.
    from twins import league
    store.create_account(get_conn, twin_id=f"league:T-15X:v{league.LEAGUE_VERSION}", bot_id="league", kind="shadow",
                         version=league.LEAGUE_VERSION, bars="alpaca_daily",
                         start_at=datetime.combine(days[-3], time(16), NEW_YORK), start_equity=100_000, config={})
    store.append_decision(get_conn, twin_id=f"league:T-15X:v{league.LEAGUE_VERSION}",
                          decided_at=datetime.combine(days[-2], time(17, 15), NEW_YORK),
                          step_at=datetime.combine(days[-2], time(16), NEW_YORK), weights={"SSO": 0.7, "BIL": 0.3})

    roles = ("member_1", "member_2", "member_3")
    night = lambda d: ai.run(get_conn, datetime.combine(d, time(17, 15), NEW_YORK), d, bars, call=fake, roles=roles,
                             start_equity=lambda bot: 90_000.0)
    first = night(days[-2])
    assert all(v.startswith("started") for v in first.values())
    assert calls == []
    second = night(days[-1])
    atlas = second[f"oracle:ai:v{ai.VERSION}"]
    assert atlas["valid"] == 2 and atlas["of"] == 3 and not atlas["missed"]
    dec = store.decisions(get_conn, f"oracle:ai:v{ai.VERSION}")[-1]
    assert abs(sum(dec["weights"].values()) - 1.0) < 1e-6 and dec["weights"]["BIL"] == pytest.approx(0.1)
    veto = store.decisions(get_conn, f"{ai.AI_BOT}:T-15X:v{league.LEAGUE_VERSION}")[-1]
    assert veto["weights"] == {"BIL": pytest.approx(0.65), "SSO": pytest.approx(0.35)}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT role, cost_usd, reply IS NULL FROM twin_votes WHERE twin_id = %s ORDER BY id",
                    (f"oracle:ai:v{ai.VERSION}",))
        votes = cur.fetchall()
    assert [v[0] for v in votes] == list(roles)
    assert votes[2][1] == pytest.approx((1000 * 0.5 + 500 * 3.0) / 1e6)        # the bad reply still costs
    assert night(days[-1])[f"oracle:ai:v{ai.VERSION}"] == "already voted for this session"

    old = ai.MONTHLY_CAP_USD
    ai.MONTHLY_CAP_USD = 0.0
    try:
        nxt = days[-1] + timedelta(days=1)
        bars2 = {s: rows + [dict(rows[-1], day=nxt)] for s, rows in bars.items()}
        out = ai.run(get_conn, datetime.combine(nxt, time(17, 15), NEW_YORK), nxt, bars2, call=fake, roles=roles,
                     start_equity=lambda bot: 90_000.0)
        assert out[f"oracle:ai:v{ai.VERSION}"] == "missed: cost cap"
        assert store.decisions(get_conn, f"oracle:ai:v{ai.VERSION}")[-1]["missed"]
    finally:
        ai.MONTHLY_CAP_USD = old
