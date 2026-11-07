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


def _call(pair, direction="short", strategy="trend"):
    return {"pair": pair, "direction": direction, "strategy": strategy, "conviction": 2,
            "reason": "momentum weak", "why_not_others": "carry is small and no fresh news"}


class FakeTransport:
    def __init__(self, *, fail=()):
        self.fail = set(fail)
        self.sent = []

    def __call__(self, url, headers, body):
        self.sent.append((url, headers, body))
        host = url.split("/")[2]
        if host in self.fail:
            raise fc.CouncilError("provider returned HTTP 503")
        if host == "generativelanguage.googleapis.com":
            pairs = [p["pair"] for p in json.loads(body["contents"][0]["parts"][0]["text"])["pack"]["pairs"]]
            return _gemini_reply({"decisions": [
                {"pair": p, "direction": "long", "strategy": "carry", "conviction": 3, "stop_atr_multiple": 2.0,
                 "sided_with": "both", "reason": "EUR trend <script>x</script> agrees https://evil.example",
                 "why_not_others": "trend is flat; carry pays"}
                for p in pairs]})
        pairs = [p["pair"] for p in json.loads(body["messages"][1]["content"])["pairs"]]
        return _openai_reply({"calls": [_call(p) for p in pairs]})


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
    assert first["strategy"] == "carry" and first["why_not_others"] == "trend is flat; carry pays"
    assert "http" not in first["reason"] and "<" not in first["reason"]
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
    # Decision-maker sees only structured council fields.
    dm_input = json.loads(transport.sent[2][2]["contents"][0]["parts"][0]["text"])
    assert set(dm_input["council"]["member_1"][0]) == {
        "pair", "direction", "strategy", "conviction", "reason", "why_not_others"}


def test_one_member_down_runs_low_confidence(keys):
    record = fc.run_council(_sheet(), today="2026-11-09", transport=FakeTransport(fail={"openrouter.ai"}))
    assert record["status"] == "shadow" and record["low_confidence"] is True
    assert any("member_2" in e for e in record["errors"])


def test_both_members_down_or_decision_maker_down_means_no_trade(keys):
    both = fc.run_council(_sheet(), today="2026-11-09", transport=FakeTransport(fail={"api.groq.com", "openrouter.ai"}))
    dm = fc.run_council(_sheet(), today="2026-11-09", transport=FakeTransport(fail={"generativelanguage.googleapis.com"}))
    assert both["status"] == dm["status"] == "no_trade"
    assert both["decisions"] == dm["decisions"] == []


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
])
def test_council_reply_must_match_schema_exactly(bad):
    with pytest.raises(fc.CouncilError):
        fc.parse_council_reply(json.dumps(bad), ["EUR_USD"])


def test_flat_with_stay_out_is_accepted():
    parsed = fc.parse_council_reply(json.dumps({"calls": [_call("EUR_USD", "flat", "stay_out")]}), ["EUR_USD"])
    assert parsed[0]["strategy"] == "stay_out"


def test_decision_stop_multiple_is_range_checked():
    reply = {"decisions": [{"pair": "EUR_USD", "direction": "long", "strategy": "trend", "conviction": 3,
                            "stop_atr_multiple": 0.2, "sided_with": "both", "reason": "", "why_not_others": ""}]}
    with pytest.raises(fc.CouncilError, match="stop_atr_multiple"):
        fc.parse_decision_reply(json.dumps(reply), ["EUR_USD"])


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
                return {"candidates": [{"content": {"parts": [{"text": '{"decisions": [ {"pair"'}]}}]}
            good = base(url, headers, body)
            text = good["candidates"][0]["content"]["parts"][0]["text"]
            good["candidates"][0]["content"]["parts"][0]["text"] = "Here you go:\n" + text + "\nDone."
            return good
        return base(url, headers, body)

    record = fc.run_council(_sheet(), today="2026-11-09", transport=transport)
    assert record["status"] == "shadow" and attempts["gemini"] == 2
    assert any("retrying once" in e for e in record["errors"])
    assert [c["attempt"] for c in record["calls"] if c["role"] == "decision_maker"] == [1, 2]


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
