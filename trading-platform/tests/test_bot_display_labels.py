from core.bot_registry import BOT_REGISTRY, bot_by_id, display_label


EXPECTED_LABELS = {
    "oracle": ("Atlas", "Atlas", "FLEET-V1 fleet (headline)", "Atlas · FLEET-V1 fleet (headline)"),
    "spy_qqq_trend": (
        "Momentum",
        "Momentum",
        "Stock momentum (experiment)",
        "Momentum · Stock momentum (experiment)",
    ),
    "jerome_macro": (
        "Atlas V2",
        "Atlas V2",
        "Equity trend core",
        "Atlas V2 · Equity trend core",
    ),
}


def test_active_bot_registry_display_labels() -> None:
    for bot_id, (display_name, short_name, subtitle, label) in EXPECTED_LABELS.items():
        entry = bot_by_id(bot_id)
        assert entry is not None
        assert entry.id == bot_id
        assert entry.display_name == display_name
        assert entry.short_name == short_name
        assert entry.subtitle == subtitle
        assert display_label(bot_id) == label

    assert set(EXPECTED_LABELS).issubset(BOT_REGISTRY)

def test_every_account_has_its_standing_code() -> None:
    """Bot 1/2/3 (and 4 for the paused Forex account) are how the accounts are
    referred to whatever their display name; the ids underneath never change."""
    codes = {bot_id: bot_by_id(bot_id).code for bot_id in ("oracle", "spy_qqq_trend", "jerome_macro", "forex_ai")}
    assert codes == {"oracle": "Bot 1", "spy_qqq_trend": "Bot 2", "jerome_macro": "Bot 3", "forex_ai": "Bot 4"}
