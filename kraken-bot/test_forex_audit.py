from datetime import date, datetime, timezone
from pathlib import Path

import forex_audit as fa
import forex_ai_strategy as fs
from forex_council import build_pack

ROW = {
    "pair": "EUR_USD", "trend": "up", "momentum_return": 0.03, "short_momentum_return": 0.01,
    "atr_pct": 0.006, "realised_vol": 0.08, "carry": {"long_rate": 0.02, "short_rate": -0.01},
    "spread_to_atr": 0.1,
}


def _good_record():
    pack = build_pack([ROW], today="2026-11-09")
    import json
    return {"pack": pack, "label_map": {"EUR_USD": "EUR_USD"},
            "calls": [{"role": "member_1", "request": {"system": "rules", "user": json.dumps(pack)}, "raw": "{}"}]}


def test_clean_record_and_real_source_have_no_findings():
    assert fa.audit_records([(date(2026, 10, 20), _good_record())]) == []
    assert fa.audit_source() == []


def test_off_schema_pack_and_key_like_strings_are_flagged():
    rec = _good_record()
    rec["pack"]["pairs"][0]["extra"] = 1
    rec["calls"][0]["raw"] = "token gsk_abcdefghijkl1234"
    found = fa.audit_records([(date(2026, 10, 20), rec)])
    assert any("off schema" in f for f in found)
    assert any("key-like string in member_1 reply" in f for f in found)


def test_older_pack_versions_are_not_rechecked_against_todays_schema():
    """Packs logged before 7 Nov 2026 used letters and no version; they were valid then."""
    old = {"pack": {"pairs": [{"label": "A"}], "calendar": "unavailable", "news": "unavailable"},
           "label_map": {"A": "EUR_USD"}, "calls": []}
    assert fa.audit_records([(date(2026, 10, 20), old)]) == []


def test_unexpected_host_in_code_is_flagged(tmp_path):
    (tmp_path / "x.py").write_text('URL = "https://evil.example.com/post"\n')
    assert fa.audit_source(tmp_path, ("x.py",)) == ["x.py: host evil.example.com is not on the allowlist"]


def test_weekly_audit_runs_saturdays_only_and_records_findings(monkeypatch):
    fs._last_audit_day = None
    seen = []
    monkeypatch.setattr(fa, "run_weekly_audit", lambda _c: ["boom"])
    import core.degradation_tracker as dt
    monkeypatch.setattr(dt, "record_degradation", lambda **k: seen.append(k) or True)
    friday = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)
    saturday = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
    assert fs._maybe_run_weekly_audit(now=friday, get_conn=object) == "not due"
    assert fs._maybe_run_weekly_audit(now=saturday, get_conn=object) == "findings=1"
    assert fs._maybe_run_weekly_audit(now=saturday, get_conn=object) == "not due"
    assert seen[0]["component"] == "forex_council" and seen[0]["bot_id"] == "forex_ai"


def test_key_pattern_needs_a_token_start():
    assert fa._has_key('x = "sk-abcdef1234567890"') and fa._has_key("gsk_ABCDEFGH12345")
    assert not fa._has_key("from core.degradation_tracker import mark_resolved")


def test_a_pack_read_back_from_jsonb_is_not_off_schema():
    """JSONB returns keys sorted (by length, then name), not in the order sent.
    7-8 Nov 2026: the weekly audit reported the 6 Nov pack off schema for this alone."""
    import json
    rec = _good_record()
    rec["pack"]["news"] = [{"source": "s", "about": "EUR_USD", "title": "t", "hours_ago": 3}]

    def jsonb(obj):          # what Postgres hands back
        if isinstance(obj, dict):
            return {k: jsonb(obj[k]) for k in sorted(obj, key=lambda k: (len(k), k))}
        return [jsonb(x) for x in obj] if isinstance(obj, list) else obj

    stored = json.loads(json.dumps(jsonb(rec)))
    assert list(stored["pack"]) != list(rec["pack"])            # order really differs
    assert fa.audit_records([(date(2026, 11, 6), stored)]) == []
    stored["pack"]["pairs"][0]["extra"] = 1                      # a real extra field still fails
    assert any("off schema" in f for f in fa.audit_records([(date(2026, 11, 6), stored)]))
