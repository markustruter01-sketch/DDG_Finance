from core.bot_registry import BOT_REGISTRY, bot_by_id, display_label


EXPECTED_LABELS = {
    "oracle": ("Atlas", "Atlas", "Global Market Indexes", "Atlas · Global Market Indexes"),
    "spy_qqq_trend": (
        "Momentum",
        "Momentum",
        "Stock Trend Cooldown",
        "Momentum · Stock Trend Cooldown",
    ),
    "jerome_macro": (
        "Bullion",
        "Bullion",
        "Precious Metals and Crypto",
        "Bullion · Precious Metals and Crypto",
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