import json

from core.bot_registry import display_label
from notifications import alert_manager, discord


def test_profitable_trade_alert_queue_uses_registry_label(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(alert_manager, "_CONFIG_FILE", tmp_path / "alert-config.json")
    monkeypatch.setattr(alert_manager, "_QUEUE_FILE", tmp_path / "alert-queue.json")
    monkeypatch.setattr(alert_manager, "_ensure_data_dir", lambda: None)
    monkeypatch.setattr(alert_manager, "_restart_flush_timer", lambda: None)

    alert_manager.enqueue_profitable_trade(
        "oracle",
        "SPY",
        pnl_pct=1.25,
        pnl_usd=125.0,
    )

    queued = json.loads((tmp_path / "alert-queue.json").read_text())
    assert queued[0]["bot_name"] == display_label("oracle")


def test_daily_discord_warning_lines_use_registry_labels(monkeypatch) -> None:
    from core import market_state
    from routes import fleet_equity

    sent_payloads = []
    monkeypatch.setattr(discord, "_WEBHOOK_URL", "configured-for-test")
    monkeypatch.setattr(discord, "_audit_start", lambda *args, **kwargs: 1)
    monkeypatch.setattr(discord, "_audit_finish", lambda *args, **kwargs: None)
    monkeypatch.setattr(discord, "_send", lambda payload, **kwargs: sent_payloads.append(payload))
    monkeypatch.setattr(discord, "_last_trade_timestamps", lambda: {})
    monkeypatch.setattr(
        fleet_equity,
        "_fetch_fleet_equity",
        lambda: {
            "fleet_total": {"pnl_24h": 0.0, "pnl_24h_pct": 0.0},
            "oracle": {"starting": 100_000.0, "pnl_24h": 0.0},
            "spy_qqq_trend": {"starting": 100_000.0, "pnl_24h": 0.0},
            "jerome_macro": {"starting": 100_000.0, "pnl_24h": 0.0},
        },
    )
    monkeypatch.setattr(
        market_state,
        "get_market_state",
        lambda **kwargs: {"regime": "BULL"},
    )

    discord.notify_daily_pnl_report()

    content = sent_payloads[0]["content"]
    for bot_id in ("oracle", "spy_qqq_trend", "jerome_macro"):
        assert f"⚠️ {display_label(bot_id)}: no trades 48h" in content