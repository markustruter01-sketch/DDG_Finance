"""The Forex page's API shapes (trading-platform/routes/forex_council_log.py), pure parts only."""
import importlib.util
import json
from datetime import date
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "trading-platform" / "routes" / "forex_council_log.py"
_spec = importlib.util.spec_from_file_location("forex_council_log", _PATH)
log = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(log)


def _v2_record():
    member = {"calls": [{"pair": "EUR_USD", "direction": "short", "strategy": "trend", "conviction": 3,
                         "reason": "falling", "why_not_others": "carry small",
                         "expected_move_pct": -0.5, "horizon_days": 5, "expected_path": "slides lower"}]}
    return {
        "pack": {"version": 2, "date": "2026-11-09", "pairs": [{"pair": "EUR_USD"}],
                 "news": [{"source": "ECB", "about": "EUR", "title": "Rates held", "hours_ago": 2}]},
        "label_map": {"EUR_USD": "EUR_USD"},
        "news_sources": [{"name": "ECB", "status": "ok (1 new)"}],
        "calls": [{"role": "member_1", "provider": "groq", "model": "m1", "raw": json.dumps(member)},
                  {"role": "member_2", "provider": "openrouter", "model": "m2", "raw": "not json"},
                  {"role": "decision_maker", "raw": "{}"}],
        "decisions": [{"pair": "EUR_USD", "direction": "short", "strategy": "trend", "conviction": 3,
                       "stop_atr_multiple": 2.0, "sided_with": "member_1", "reason": "agree",
                       "why_not_others": "no event", "baseline": "short"}],
        "errors": ["member_2: reply is not valid JSON"],
        "low_confidence": True,
    }


def test_day_detail_shows_news_members_decisions_and_trades():
    d = log.day_detail(date(2026, 11, 9), "shadow", _v2_record(), "abc", {"opens": 1})
    assert d["news"][0]["title"] == "Rates held" and d["news_count"] == 1
    assert d["members"]["member_1"]["calls"][0]["why_not_others"] == "carry small"
    m1 = d["members"]["member_1"]["calls"][0]
    assert (m1["expected_move_pct"], m1["horizon_days"], m1["expected_path"]) == (-0.5, 5, "slides lower")
    assert "member_2" not in d["members"]  # unreadable reply is left out, not guessed
    assert d["decisions"][0]["sided_with"] == "member_1"
    assert d["trades"] == [{"pair": "EUR_USD", "direction": "short", "strategy": "trend", "conviction": 3,
                            "outcome": None}]
    assert d["council_version"] == 2
    assert d["executed"] is True and d["pack_version"] == 2


def test_old_lettered_records_map_back_to_pairs():
    old = {"pack": {"pairs": [], "calendar": "unavailable", "news": "unavailable"},
           "label_map": {"A": "USD_JPY"},
           "calls": [{"role": "member_1", "raw": json.dumps({"calls": [
               {"label": "A", "direction": "long", "conviction": 2, "reason": "x"}]})}],
           "decisions": [{"pair": "USD_JPY", "direction": "long"}]}
    d = log.day_detail(date(2026, 10, 20), "shadow", old, "def", None)
    assert d["members"]["member_1"]["calls"][0]["pair"] == "USD_JPY"
    assert d["news"] == [] and d["pack_version"] == 1 and d["executed"] is False
