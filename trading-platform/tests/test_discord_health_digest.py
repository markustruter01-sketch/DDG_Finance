from __future__ import annotations

from datetime import datetime, timedelta, timezone

from notifications import discord


def _healthy_report():
    return {
        "overall": "PASS",
        "results": [
            {
                "name": "strategy_positions_have_covering_stops",
                "status": "PASS",
                "message": "All positions are covered.",
                "actual": {"missing_stops": []},
                "difference": {},
            }
        ],
    }


def test_healthy_digest_is_explicit_and_includes_operational_state(monkeypatch):
    now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(discord, "run_all_invariants", _healthy_report, raising=False)
    monkeypatch.setattr("core.invariants.run_all_invariants", lambda **_: _healthy_report())
    monkeypatch.setattr("core.degradation_tracker.get_recent_events", lambda **_: [])
    monkeypatch.setattr(
        discord,
        "_digest_database_state",
        lambda: {
            "readable": True,
            "cycles": [
                {
                    "bot_id": "oracle",
                    "last_success_at": now - timedelta(seconds=42),
                    "status": "success",
                    "consecutive_failures": 0,
                }
            ],
            "reconciliation": {
                "run_ts": now - timedelta(minutes=2),
                "clean": True,
                "flags": [],
            },
        },
    )
    monkeypatch.setattr(
        "core.runner_heartbeat.get_runner_status",
        lambda **_: {"verdict": "ALIVE", "age_seconds": 4},
    )

    digest = discord.build_daily_health_digest(now=now)

    assert "Overall: PASS" in digest
    assert "Currently failing invariants: none" in digest
    assert "oracle: 42s" in digest
    assert "Runner heartbeat: ALIVE age=4s" in digest
    assert "Reconciliation: CLEAN" in digest
    assert "Recovered conditions: none" in digest


def test_digest_delivery_uses_published_policy(monkeypatch):
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    monkeypatch.setattr(discord, "_WEBHOOK_URL", "https://discord.example.test/hook")
    captured = []
    monkeypatch.setattr(
        discord.requests,
        "post",
        lambda _url, **kwargs: (
            captured.append(kwargs["json"]) or type("Response", (), {"status_code": 204})()
        ),
    )
    monkeypatch.setattr(discord, "build_daily_health_digest", lambda: "Overall: PASS")
    monkeypatch.setattr(discord, "_audit_start", lambda *_: 7)
    completed = []
    monkeypatch.setattr(
        discord,
        "_audit_finish",
        lambda event_id, status, **details: completed.append((event_id, status, details)),
    )

    discord.notify_daily_health_digest()

    assert captured[0]["content"].startswith("[environment: published]")
    assert completed == [(7, "sent", {"http_status": 204})]