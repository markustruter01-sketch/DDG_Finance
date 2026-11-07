from __future__ import annotations

import json

import pytest

import forex_council as fc
import forex_quant_desk as qd
from test_forex_quant_desk import _candles, _trend


def _sheet():
    rows = []
    for i, pair in enumerate(qd.FOREX_PAIRS):
        row = qd.signal_row(
            pair,
            _candles(_trend(1.0 + i, 0.001 if i % 2 else -0.001)),
            financing={"longRate": "-0.03", "shortRate": "0.01"},
            spread=0.0002,
        )
        row["baseline"] = qd.baseline_call(row)
        rows.append(row)
    return rows


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter")
    monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "test-gemini")
    monkeypatch.setitem(fc.PROVIDERS["member_2"], "model", "test/model:free")
    monkeypatch.setitem(fc.PROVIDERS["member_2"], "provider_only", ["test-host"])


def _openai_reply(obj):
    return {"choices": [{"message": {"content": json.dumps(obj)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def _gemini_reply(obj):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 8}}


NEWS = {
    "headlines": [{"source": "European Central Bank", "about": "EUR", "title": "ECB holds rates", "hours_ago": 3}],
    "sources": [{"name": "European Central Bank", "status": "ok (1 new)"}],
}


def _call(pair, direction="short", strategy="trend", conviction=2, stop=2.0):
    return {"pair": pair, "direction": direction, "strategy": strategy, "conviction": conviction,
            "stop_atr_multiple": stop,
            "reason": "momentum weak", "why_not_others": "carry is small and no fresh news",
            "expected_move_pct": -0.8, "horizon_days": 5, "expected_path": "drifts lower as the dollar firms"}


class FakeTransport:
    """All three members answer; each host's direction can be set."""
    def __init__(self, *, fail=(), dirs=None):
        self.fail = set(fail)
        self.dirs = dirs or {}
        self.sent = []

    def __call__(self, url, headers, body):
        self.sent.append((url, headers, body))
        host = url.split("/")[2]
        if host in self.fail:
            raise fc.CouncilError("provider returned HTTP 503")
        direction = self.dirs.get(host, "long")
        strategy = "stay_out" if direction == "flat" else "carry"
        if host == "generativelanguage.googleapis.com":
            pairs = [p["pair"] for p in json.loads(body["contents"][0]["parts"][0]["text"])["pairs"]]
            return _gemini_reply({"calls": [
                {**_call(p, direction, strategy, conviction=3, stop=1.5),
                 "reason": "EUR trend <script>x</script> agrees https://evil.example",
                 "why_not_others": "trend is flat; carry pays",
                 "expected_move_pct": 0.6, "horizon_days": 10, "expected_path": "grinds up while rates hold"}
                for p in pairs]})
        pairs = [p["pair"] for p in json.loads(body["messages"][1]["content"])["pairs"]]
        return _openai_reply({"calls": [_call(p, direction, strategy) for p in pairs]})


def test_pack_has_real_pairs_date_news_and_matches_the_allowlist():
    pack = fc.build_pack(_sheet(), news=NEWS["headlines"], today="2026-11-09")
    assert [p["pair"] for p in pack["pairs"]] == sorted(qd.FOREX_PAIRS)
    assert pack["date"] == "2026-11-09" and pack["version"] == fc.PACK_VERSION
    assert pack["news"][0]["title"] == "ECB holds rates"
    assert tuple(pack["pairs"][0]) == fc.PACK_PAIR_FIELDS


def test_extra_field_or_text_in_pack_is_blocked():
    pack = fc.build_pack(_sheet(), today="2026-11-09")
    pack["pairs"][0]["account_nav"] = 100000
    with pytest.raises(fc.CouncilError, match="allowlist"):
        fc.validate_pack(pack)
    pack = fc.build_pack(_sheet(), today="2026-11-09")
    pack["news"] = [{"source": "x", "about": "USD", "title": "see https://example.com", "hours_ago": 1}]
    with pytest.raises(fc.CouncilError):
        fc.validate_pack(pack)
    with pytest.raises(fc.CouncilError, match="date"):
        fc.build_pack(_sheet(), today="")


@pytest.mark.parametrize("text", ["sk-abcdefghijkl", "AIzaSyABCDEFGHIJ", "ghp_abcdefghijklmn",
                                  "postgres://u:p@h/db", "me@example.com"])
def test_scanner_blocks_keys_urls_and_emails(text):
    with pytest.raises(fc.CouncilError, match="scanner"):
        fc.scan_outbound(json.dumps({"x": text}))


def test_scanner_allows_pair_names_and_dates():
    fc.scan_outbound(json.dumps({"pair": "EUR_USD", "date": "2026-11-09"}))


def test_full_cycle_records_strategy_and_why_and_cleans_reasons(keys):
    transport = FakeTransport()
    record = fc.run_council(_sheet(), news=NEWS, today="2026-11-09", transport=transport)
    assert record["status"] == "shadow" and record["errors"] == []
    assert record["low_confidence"] is False
    assert record["news_sources"] == NEWS["sources"]
    assert {d["pair"] for d in record["decisions"]} == set(qd.FOREX_PAIRS)
    first = record["decisions"][0]
    assert first["outcome"] == "3-0" and first["half_size"] is False and first["direction"] == "long"
    assert first["strategy"] == "carry" and first["why_not_others"] == "trend is flat; carry pays"  # most confident: member_3
    assert "http" not in first["reason"] and "<" not in first["reason"]
    assert first["stop_atr_multiple"] == 1.5 and first["conviction"] == 2  # tightest stop, lowest conviction
    assert record["council_version"] == 3
    hosts = [url.split("/")[2] for url, _, _ in transport.sent]
    assert hosts == ["api.groq.com", "openrouter.ai", "generativelanguage.googleapis.com"]
    # The models see the headlines and the strategy menu.
    member_input = json.loads(transport.sent[0][2]["messages"][1]["content"])
    assert member_input["news"][0]["title"] == "ECB holds rates"
    assert "mean_reversion" in transport.sent[0][2]["messages"][0]["content"]
    # Keys only in headers, never in URLs or bodies.
    for url, headers, body in transport.sent:
        assert "test-" not in url and "test-groq" not in json.dumps(body)
    assert transport.sent[2][1]["x-goog-api-key"] == "test-gemini"
    assert transport.sent[1][2]["provider"] == {"only": ["test-host"], "allow_fallbacks": False}
    assert "response_format" not in transport.sent[1][2]
    assert transport.sent[0][2]["response_format"] == {"type": "json_object"}
    assert all(h["User-Agent"] == fc.USER_AGENT for _, h, _ in transport.sent)
    # All three see the same pack and nothing from each other.
    gemini_input = json.loads(transport.sent[2][2]["contents"][0]["parts"][0]["text"])
    assert gemini_input == member_input


def test_one_member_down_two_must_agree(keys):
    agree = fc.run_council(_sheet(), today="2026-11-09", transport=FakeTransport(fail={"openrouter.ai"}))
    assert agree["status"] == "shadow" and agree["low_confidence"] is True
    assert agree["decisions"][0]["outcome"] == "2-0" and agree["decisions"][0]["half_size"] is True
    assert any("member_2" in e for e in agree["errors"])
    split = fc.run_council(_sheet(), today="2026-11-09", transport=FakeTransport(
        fail={"openrouter.ai"}, dirs={"api.groq.com": "short"}))
    assert all(d["outcome"] == "split" and d["direction"] == "flat" for d in split["decisions"])


def test_two_members_down_means_no_trade(keys):
    record = fc.run_council(_sheet(), today="2026-11-09", transport=FakeTransport(fail={"api.groq.com", "openrouter.ai"}))
    assert record["status"] == "no_trade" and record["decisions"] == []
    assert any("only 1 of 3" in e for e in record["errors"])


def _view(direction, strategy="trend", conviction=2, stop=2.0, reason=""):
    c = {**_call("EUR_USD", direction, strategy, conviction, stop), "reason": reason}
    return [fc.parse_council_reply(json.dumps({"calls": [c]}), ["EUR_USD"])[0]]


def test_tally_two_one_trades_half_size_with_tightest_stop():
    d = fc.tally({"member_1": _view("long", "trend", 4, 3.0, "m1"), "member_2": _view("short", "carry"),
                  "member_3": _view("long", "event", 2, 1.5, "m3")}, ["EUR_USD"])[0]
    assert (d["direction"], d["outcome"], d["half_size"]) == ("long", "2-1", True)
    assert d["stop_atr_multiple"] == 1.5 and d["conviction"] == 2
    assert d["strategy"] == "trend" and d["reason"] == "m1"  # winners' strategies differ: most confident winner's
    assert d["votes"] == {"member_1": "long", "member_2": "short", "member_3": "long"}


def test_tally_split_stays_out_and_flat_majority_is_flat():
    split = fc.tally({"member_1": _view("long"), "member_2": _view("short"),
                      "member_3": _view("flat", "stay_out")}, ["EUR_USD"])[0]
    assert (split["direction"], split["outcome"], split["half_size"]) == ("flat", "split", False)
    assert "expected_move_pct" not in split  # no shared prediction to score
    flat = fc.tally({"member_1": _view("flat", "stay_out"), "member_2": _view("flat", "stay_out"),
                     "member_3": _view("long")}, ["EUR_USD"])[0]
    assert (flat["direction"], flat["outcome"], flat["half_size"]) == ("flat", "2-1", False)


def test_tally_most_common_winning_strategy():
    d = fc.tally({"member_1": _view("short", "trend"), "member_2": _view("short", "carry", 5),
                  "member_3": _view("short", "trend")}, ["EUR_USD"])[0]
    assert (d["strategy"], d["outcome"], d["half_size"]) == ("trend", "3-0", False)


def test_unpinned_openrouter_and_missing_keys_fail_closed(monkeypatch):
    for env in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_GEMINI_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    record = fc.run_council(_sheet(), today="2026-11-09", transport=FakeTransport())
    assert record["status"] == "no_trade"
    assert any("not configured" in e for e in record["errors"])


@pytest.mark.parametrize("bad", [
    {"calls": []},
    {"calls": [{**_call("GBP_USD")}]},
    {"calls": [{**_call("EUR_USD"), "direction": "buy"}]},
    {"calls": [{**_call("EUR_USD"), "conviction": 9}]},
    {"calls": [{**_call("EUR_USD"), "size": 10}]},
    {"calls": [{**_call("EUR_USD"), "strategy": "astrology"}]},
    {"calls": [_call("EUR_USD", direction="flat", strategy="trend")]},
    {"calls": [_call("EUR_USD", direction="long", strategy="stay_out")]},
    {"calls": [], "note": "ignore previous instructions"},
    {"calls": [{**_call("EUR_USD"), "expected_move_pct": 25}]},
    {"calls": [{**_call("EUR_USD"), "expected_move_pct": "big"}]},
    {"calls": [{**_call("EUR_USD"), "horizon_days": 0}]},
    {"calls": [{**_call("EUR_USD"), "horizon_days": 60}]},
    {"calls": [{k: v for k, v in _call("EUR_USD").items() if k != "expected_path"}]},
])
def test_council_reply_must_match_schema_exactly(bad):
    with pytest.raises(fc.CouncilError):
        fc.parse_council_reply(json.dumps(bad), ["EUR_USD"])


def test_flat_with_stay_out_is_accepted():
    parsed = fc.parse_council_reply(json.dumps({"calls": [_call("EUR_USD", "flat", "stay_out")]}), ["EUR_USD"])
    assert parsed[0]["strategy"] == "stay_out"


def test_call_stop_multiple_is_range_checked():
    with pytest.raises(fc.CouncilError, match="stop_atr_multiple"):
        fc.parse_council_reply(json.dumps({"calls": [_call("EUR_USD", stop=0.2)]}), ["EUR_USD"])


def test_real_transport_refuses_hosts_off_the_allowlist():
    with pytest.raises(fc.CouncilError, match="allowlist"):
        fc._http_post("https://evil.example/v1", {}, {})
    with pytest.raises(fc.CouncilError, match="allowlist"):
        fc._http_post("http://api.groq.com/x", {}, {})


def test_one_retry_then_success_and_empty_reply_is_explained(keys):
    calls = []

    def flaky(url, headers, body):
        calls.append(url)
        if len(calls) == 1:
            return {"choices": [{"finish_reason": "length", "message": {"content": None}}]}
        return _openai_reply({"calls": [_call("EUR_USD", "flat", "stay_out")]})

    record = fc.call_model("member_1", "s", "{}", transport=flaky)
    assert len(calls) == 2 and "flat" in record["raw"]

    def always_empty(url, headers, body):
        return {"choices": [{"finish_reason": "length", "message": {"content": ""}}]}

    with pytest.raises(fc.CouncilError, match="finish=length"):
        fc.call_model("member_1", "s", "{}", transport=always_empty)


def test_malformed_reply_gets_one_repair_attempt_and_prose_is_tolerated(keys):
    attempts = {"gemini": 0}
    base = FakeTransport()

    def transport(url, headers, body):
        if "generativelanguage" in url:
            attempts["gemini"] += 1
            if attempts["gemini"] == 1:
                return {"candidates": [{"content": {"parts": [{"text": '{"calls": [ {"pair"'}]}}]}
            good = base(url, headers, body)
            text = good["candidates"][0]["content"]["parts"][0]["text"]
            good["candidates"][0]["content"]["parts"][0]["text"] = "Here you go:\n" + text + "\nDone."
            return good
        return base(url, headers, body)

    record = fc.run_council(_sheet(), today="2026-11-09", transport=transport)
    assert record["status"] == "shadow" and attempts["gemini"] == 2
    assert any("retrying once" in e for e in record["errors"])
    assert [c["attempt"] for c in record["calls"] if c["role"] == "member_3"] == [1, 2]


def test_transport_failure_records_only_the_exception_class(monkeypatch):
    """A failed request names its cause (e.g. ReadTimeout) but never the URL or key."""
    import httpx

    class Boom:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, json=None):
            raise httpx.ReadTimeout(f"timed out calling {url} with {headers}")

    monkeypatch.setattr(fc.httpx, "Client", Boom)
    with pytest.raises(fc.CouncilError) as err:
        fc._http_post("https://openrouter.ai/api/v1/chat/completions", {"Authorization": "Bearer sk-secret"}, {})
    msg = str(err.value)
    assert msg == "provider request failed (ReadTimeout)"
    assert "sk-secret" not in msg and "openrouter" not in msg


def test_every_call_and_decision_carries_a_prediction(keys):
    record = fc.run_council(_sheet(), news=NEWS, today="2026-11-09", transport=FakeTransport())
    d = record["decisions"][0]
    assert (d["expected_move_pct"], d["horizon_days"], d["expected_path"]) == (0.6, 10, "grinds up while rates hold")
    parsed = fc.parse_council_reply(json.dumps({"calls": [_call("EUR_USD")]}), ["EUR_USD"])
    assert parsed[0]["expected_move_pct"] == -0.8 and parsed[0]["horizon_days"] == 5
