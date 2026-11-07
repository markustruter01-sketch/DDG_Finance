from datetime import datetime, timezone

import pytest

import forex_news as fn

NOW = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Fed holds rates &amp; signals patience https://evil.example</title><pubDate>Mon, 09 Nov 2026 19:00:00 GMT</pubDate></item>
<item><title><![CDATA[<b>Statement</b> on balance sheet]]></title><pubDate>Mon, 09 Nov 2026 18:00:00 GMT</pubDate></item>
<item><title>Old news</title><pubDate>Mon, 02 Nov 2026 18:00:00 GMT</pubDate></item>
<item><title>No date</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>ECB press conference</title><updated>2026-11-09T13:45:00Z</updated></entry></feed>"""

GDELT = b'{"articles":[{"title":"Dollar slips as jobs data disappoints","seendate":"20261109T200000Z","domain":"example.com"}]}'


def fake_fetch(responses):
    def fetch(url):
        for key, value in responses.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise fn.NewsError("HTTP 404")
    return fetch


def test_titles_are_plain_text_only():
    assert fn.clean_title("<b>Hi</b> see https://x.y/z and me@a.io " + "A" * 50) == "Hi see and"


def test_rss_and_atom_parse_with_dates():
    items = fn.parse_feed(RSS)
    assert items[0][0] == "Fed holds rates & signals patience"
    assert items[1][0] == "Statement on balance sheet"
    assert fn.parse_feed(ATOM)[0][0] == "ECB press conference"
    with pytest.raises(fn.NewsError):
        fn.parse_feed(b"not xml")


def test_gather_keeps_fresh_dated_headlines_and_reports_each_source():
    out = fn.gather_news(fetch=fake_fetch({
        "federalreserve.gov": RSS, "ecb.europa.eu": ATOM, "gdeltproject": GDELT,
        "bankofengland": fn.NewsError("HTTP 503"), "boj.or.jp": RuntimeError("boom"),
    }), now=NOW)
    titles = [h["title"] for h in out["headlines"]]
    assert "Fed holds rates & signals patience" in titles
    assert "Old news" not in titles and "No date" not in titles  # too old / undated
    assert "Dollar slips as jobs data disappoints (example.com)" in titles
    fed = next(h for h in out["headlines"] if h["source"] == "Federal Reserve")
    assert fed["about"] == "USD" and fed["hours_ago"] == 3
    status = {s["name"]: s["status"] for s in out["sources"]}
    assert status["Federal Reserve"] == "ok (2 new)"
    assert status["Bank of England"] == "failed: HTTP 503"
    assert status["Bank of Japan"] == "failed: RuntimeError"
    assert [h["hours_ago"] for h in out["headlines"]] == sorted(h["hours_ago"] for h in out["headlines"])


def test_every_source_failing_still_returns_cleanly():
    out = fn.gather_news(fetch=fake_fetch({}), now=NOW)
    assert out["headlines"] == [] and all(s["status"].startswith("failed") for s in out["sources"])


def test_real_fetch_refuses_hosts_off_the_allowlist():
    with pytest.raises(fn.NewsError, match="allowlist"):
        fn._http_get("https://evil.example/feed")
    with pytest.raises(fn.NewsError, match="allowlist"):
        fn._http_get("http://www.federalreserve.gov/feeds/press_all.xml")


def test_headlines_fit_the_council_pack():
    import forex_council as fc
    out = fn.gather_news(fetch=fake_fetch({"federalreserve.gov": RSS, "gdeltproject": GDELT}), now=NOW)
    row = {"pair": "EUR_USD", "trend": "up", "momentum_return": 0.03, "short_momentum_return": 0.01,
           "atr_pct": 0.006, "realised_vol": 0.08, "carry": {"long_rate": 0.02, "short_rate": -0.01},
           "spread_to_atr": 0.1}
    pack = fc.build_pack([row], news=out["headlines"], today="2026-11-09")
    assert len(pack["news"]) == len(out["headlines"]) > 0
