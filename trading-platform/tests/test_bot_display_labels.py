from core.bot_registry import BOT_REGISTRY, bot_by_id, display_label


EXPECTED_LABELS = {
    "oracle": ("Atlas", "Atlas", "Gearbox G4 (headline)", "Atlas · Gearbox G4 (headline)"),
    "spy_qqq_trend": (
        "Momentum",
        "Momentum",
        "G4 + DBMF (forward test)",
        "Momentum · G4 + DBMF (forward test)",
    ),
    "jerome_macro": (
        "Bullion",
        "Bullion",
        "Precious Metals and Crypto (research)",
        "Bullion · Precious Metals and Crypto (research)",
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