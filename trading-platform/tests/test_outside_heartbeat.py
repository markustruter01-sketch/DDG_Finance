"""Outside heartbeat (core/outside_heartbeat.py): no network."""
import time

from core import outside_heartbeat as hb


def test_nothing_is_sent_without_a_secret_or_outside_the_published_deployment(monkeypatch):
    sent = []
    monkeypatch.setattr(hb, "_send", sent.append)
    monkeypatch.setattr(hb, "_last", {})
    monkeypatch.delenv("HEARTBEAT_URL_RUNNER", raising=False)
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    assert hb.ping("RUNNER") is False
    monkeypatch.setenv("HEARTBEAT_URL_RUNNER", "https://example.invalid/ping/abc")
    monkeypatch.delenv("REPLIT_DEPLOYMENT")
    assert hb.ping("RUNNER") is False
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    monkeypatch.setenv("HEARTBEAT_URL_RUNNER", "http://not-https.invalid/x")
    assert hb.ping("RUNNER") is False
    assert sent == []


def test_ping_is_sent_once_a_minute_per_signal_and_never_raises(monkeypatch):
    sent = []
    monkeypatch.setattr(hb, "_send", sent.append)
    monkeypatch.setattr(hb, "_last", {})
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    monkeypatch.setenv("HEARTBEAT_URL_RUNNER", "https://example.invalid/ping/abc")
    monkeypatch.setenv("HEARTBEAT_URL_API", "https://example.invalid/ping/def")
    assert hb.ping("RUNNER") and hb.ping("API")
    assert hb.ping("RUNNER") is False                      # inside the minute
    for _ in range(50):
        if len(sent) == 2:
            break
        time.sleep(0.01)
    assert sorted(sent) == ["https://example.invalid/ping/abc", "https://example.invalid/ping/def"]
    hb._send("https://127.0.0.1:1/unreachable")            # a failed ping is swallowed
