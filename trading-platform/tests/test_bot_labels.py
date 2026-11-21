"""Screens call each bot "Bot N · Name" (dashboard lib/bot-identity botLabel, Markus 21 Nov 2026).
The back-end ids (oracle, jerome_macro, ...) never change; the numbers must stay fixed and unique."""
from core.bot_registry import BOT_REGISTRY, to_dict_list

FIXED = {"oracle": "Bot 1", "spy_qqq_trend": "Bot 2", "jerome_macro": "Bot 3", "forex_ai": "Bot 4"}


def test_every_bot_keeps_its_fixed_number():
    assert {bot_id: e.code for bot_id, e in BOT_REGISTRY.items() if bot_id in FIXED} == FIXED


def test_numbers_are_unique_and_every_bot_has_a_name():
    rows = to_dict_list()
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes))
    assert all(r["code"].startswith("Bot ") and r["display_name"].strip() for r in rows)
