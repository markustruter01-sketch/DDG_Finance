from __future__ import annotations

from notifications import discord


class _Response:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _capture_audit(monkeypatch):
    started = []
    completed = []

    def start(alert_type, title):
        started.append((alert_type, title))
        return 41

    def finish(event_id, status, **details):
        completed.append((event_id, status, details))

    monkeypatch.setattr(discord, "_audit_start", start)
    monkeypatch.setattr(discord, "_audit_finish", finish)
    return started, completed


def test_missing_webhook_is_recorded_as_skipped(monkeypatch):
    started, completed = _capture_audit(monkeypatch)
    monkeypatch.setattr(discord, "_WEBHOOK_URL", None)
    monkeypatch.setattr(
        discord.requests,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("HTTP must not be called without a webhook")
        ),
    )

    discord._send(
        {"content": "test"},
        alert_type="critical",
        title="Runner unavailable",
    )

    assert started == [("critical", "Runner unavailable")]
    assert completed[0][0:2] == (41, "skipped_not_configured")


def test_successful_webhook_is_recorded_as_sent(monkeypatch):
    started, completed = _capture_audit(monkeypatch)
    monkeypatch.setattr(discord, "_WEBHOOK_URL", "https://discord.example.test/hook")
    monkeypatch.setattr(
        discord.requests,
        "post",
        lambda *_args, **_kwargs: _Response(204),
    )

    discord._send(
        {"content": "test"},
        alert_type="critical",
        title="Runner unavailable",
    )

    assert started == [("critical", "Runner unavailable")]
    assert completed == [(41, "sent", {"http_status": 204})]


def test_http_failure_is_recorded_without_webhook_response_body(monkeypatch):
    _, completed = _capture_audit(monkeypatch)
    monkeypatch.setattr(discord, "_WEBHOOK_URL", "https://discord.example.test/hook")
    monkeypatch.setattr(
        discord.requests,
        "post",
        lambda *_args, **_kwargs: _Response(503, "provider details"),
    )

    discord._send(
        {"content": "test"},
        alert_type="critical",
        title="Runner unavailable",
    )

    assert completed == [
        (41, "failed", {"http_status": 503, "error": "HTTP 503"})
    ]


def test_network_failure_is_recorded(monkeypatch):
    _, completed = _capture_audit(monkeypatch)
    monkeypatch.setattr(discord, "_WEBHOOK_URL", "https://discord.example.test/hook")

    def fail(*_args, **_kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(discord.requests, "post", fail)

    discord._send(
        {"content": "test"},
        alert_type="critical",
        title="Runner unavailable",
    )

    assert completed == [
        (41, "failed", {"error": "TimeoutError"})
    ]


def test_network_failure_never_persists_webhook_url(monkeypatch):
    _, completed = _capture_audit(monkeypatch)
    webhook_url = "https://discord.example.test/secret-path"
    monkeypatch.setattr(discord, "_WEBHOOK_URL", webhook_url)

    def fail(*_args, **_kwargs):
        raise RuntimeError(f"request failed for {webhook_url}")

    monkeypatch.setattr(discord.requests, "post", fail)

    discord._send({"content": "test"}, alert_type="critical", title="Test")

    assert completed == [(41, "failed", {"error": "RuntimeError"})]
    assert webhook_url not in repr(completed)


def test_daily_report_without_webhook_is_audited_as_skipped(monkeypatch):
    started, completed = _capture_audit(monkeypatch)
    monkeypatch.setattr(discord, "_WEBHOOK_URL", None)

    discord.notify_daily_pnl_report()

    assert started == [("daily_report", "Daily fleet P&L report")]
    assert completed[0][0:2] == (41, "skipped_not_configured")


def test_thread_start_failure_finalizes_attempt(monkeypatch):
    started, completed = _capture_audit(monkeypatch)

    class _BrokenThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr(discord.threading, "Thread", _BrokenThread)

    discord._send_async(
        {"content": "test"},
        alert_type="critical",
        title="Runner unavailable",
    )

    assert started == [("critical", "Runner unavailable")]
    assert completed == [(41, "failed", {"error": "RuntimeError"})]