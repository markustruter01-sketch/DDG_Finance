from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import timedelta, date, datetime, timezone

import forex_ai_strategy as fas
import forex_scorecard as sc


def _candle(start_utc: str, close: float):
    return {"time": start_utc, "complete": True, "mid": {"c": str(close)}}


def test_candle_maps_to_the_new_york_day_it_closes_on():
    # Starts Thu 15 Oct 17:00 New York (21:00 UTC) -> closes Fri 16 Oct.
    # Starts Sun 18 Oct 17:00 New York -> closes Mon 19 Oct.
    out = sc.closes_by_day([_candle("2026-10-15T21:00:00.000000000Z", 1.1),
                            _candle("2026-10-18T21:00:00.000000000Z", 1.2),
                            {"time": "2026-10-19T21:00:00Z", "complete": False, "mid": {"c": "9"}}])
    assert out == {date(2026, 10, 16): 1.1, date(2026, 10, 19): 1.2}


def _record(baseline, decision, m1, m2):
    labels = {"Pair A": "EUR_USD"}
    def raw(d):
        return json.dumps({"calls": [{"label": "Pair A", "direction": d, "conviction": 3, "reason": "x"}]})
    return {
        "status": "shadow", "label_map": labels, "baseline": {"EUR_USD": baseline},
        "decisions": [{"pair": "EUR_USD", "direction": decision}],
        "calls": [{"role": "member_1", "raw": raw(m1)}, {"role": "member_2", "raw": "not json"},
                  {"role": "member_2", "raw": raw(m2)}],
    }


def test_scores_each_source_only_at_matured_horizons():
    d0, d1, d2 = date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)
    closes = {"EUR_USD": {d0: 1.00, d1: 1.01, d2: 0.99}}
    card = sc.score([(d0, _record("long", "short", "long", "flat"))], closes)
    s = card["sources"]
    assert s["baseline"]["1d"] == {"calls": 1, "hit_rate_pct": 100.0, "avg_return_pct": 1.0}
    assert s["decision_maker"]["1d"]["hit_rate_pct"] == 0.0
    assert s["member_1"]["1d"]["calls"] == 1
    assert s["member_2"]["1d"]["calls"] == 0          # flat is not a call; bad reply skipped
    assert s["baseline"]["5d"]["calls"] == 0          # not matured
    assert card["days"] == {"logged": 1, "shadow": 1, "no_trade": 0, "low_confidence": 0}


def test_weekly_job_runs_on_saturday_only_and_never_raises():
    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): pass
        def fetchall(self): return [(date(2026, 10, 16), _record("long", "long", "long", "long"))]

    class Conn:
        def cursor(self): return Cur()

    @contextmanager
    def get_conn():
        yield Conn()

    class Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def daily_candles(self, pair, count):
            return [_candle("2026-10-15T21:00:00Z", 1.0), _candle("2026-10-18T21:00:00Z", 1.02)]

    fas._last_scorecard_day = None
    fri = datetime(2026, 10, 16, 22, tzinfo=timezone.utc)
    sat = datetime(2026, 10, 17, 14, tzinfo=timezone.utc)
    assert fas._maybe_log_weekly_scorecard(Client, now=fri, get_conn=get_conn) == "not due"
    assert fas._maybe_log_weekly_scorecard(Client, now=sat, get_conn=get_conn) == "logged"
    assert fas._maybe_log_weekly_scorecard(Client, now=sat, get_conn=get_conn) == "not due"
    fas._last_scorecard_day = None

    def broken():
        raise RuntimeError("down")
    assert fas._maybe_log_weekly_scorecard(broken, now=sat, get_conn=get_conn).startswith("failed")


def test_new_records_score_members_by_pair_and_decisions_by_strategy():
    d0, d1 = date(2026, 11, 9), date(2026, 11, 10)
    closes = {"EUR_USD": {d0: 1.00, d1: 1.02}, "USD_JPY": {d0: 150.0, d1: 151.5}}
    member = json.dumps({"calls": [
        {"pair": "EUR_USD", "direction": "long", "strategy": "trend", "conviction": 3, "reason": "", "why_not_others": ""},
        {"pair": "USD_JPY", "direction": "short", "strategy": "carry", "conviction": 3, "reason": "", "why_not_others": ""}]})
    record = {
        "status": "shadow", "label_map": {"EUR_USD": "EUR_USD", "USD_JPY": "USD_JPY"},
        "baseline": {"EUR_USD": "flat", "USD_JPY": "flat"},
        "decisions": [{"pair": "EUR_USD", "direction": "long", "strategy": "trend", "conviction": 5},
                      {"pair": "USD_JPY", "direction": "short", "strategy": "carry", "conviction": 2}],
        "calls": [{"role": "member_1", "raw": member}],
    }
    card = sc.score([(d0, record)], closes)
    assert card["convictions"]["5"]["1d"]["hit_rate_pct"] == 100.0
    assert card["convictions"]["2"]["1d"]["hit_rate_pct"] == 0.0
    assert card["convictions"]["3"]["1d"]["calls"] == 0
    assert card["sources"]["member_1"]["1d"] == {"calls": 2, "hit_rate_pct": 50.0, "avg_return_pct": 0.5}
    assert card["strategies"]["trend"]["1d"]["hit_rate_pct"] == 100.0
    assert card["strategies"]["carry"]["1d"]["hit_rate_pct"] == 0.0
    assert card["strategies"]["event"]["1d"]["calls"] == 0


def test_predictions_are_scored_against_the_actual_move_at_their_own_horizon():
    days = [date(2026, 11, 9) + timedelta(days=i) for i in range(4)]
    closes = {"EUR_USD": dict(zip(days, [1.00, 1.01, 1.02, 1.03]))}
    member = json.dumps({"calls": [{"pair": "EUR_USD", "direction": "long", "strategy": "trend", "conviction": 3,
                                    "reason": "", "why_not_others": "", "expected_move_pct": 1.0,
                                    "horizon_days": 2, "expected_path": ""}]})
    record = {
        "status": "shadow", "label_map": {"EUR_USD": "EUR_USD"}, "baseline": {"EUR_USD": "flat"},
        "decisions": [{"pair": "EUR_USD", "direction": "short", "strategy": "trend",
                       "expected_move_pct": -0.5, "horizon_days": 20}],  # not matured: left out
        "calls": [{"role": "member_1", "raw": member}],
    }
    old = {"status": "shadow", "decisions": [{"pair": "EUR_USD", "direction": "long", "strategy": "trend"}]}
    card = sc.score([(days[0], record), (days[1], old)], closes)
    p = card["predictions"]
    assert p["member_1"] == {"predictions": 1, "direction_right_pct": 100.0, "avg_predicted_pct": 1.0,
                             "avg_actual_pct": 2.0, "avg_miss_pct": 1.0}
    assert p["decision_maker"]["predictions"] == 0 and p["member_2"]["avg_miss_pct"] is None
