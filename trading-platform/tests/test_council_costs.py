"""Council AI cost per month, read from the token counts in the decision ledger."""
from datetime import date

from routes.forex_council_log import council_costs


def _call(model, i, o):
    return {"model": model, "usage": {"in": i, "out": o}}


def test_costs_by_month_and_unpriced_calls_are_not_counted_as_free():
    rows = [
        (date(2026, 11, 19), {"calls": [_call("openai/gpt-oss-120b", 1_000_000, 1_000_000),       # 0.15 + 0.60
                                        _call("gemini-3-flash-preview", 1_000_000, 0),            # 0.50
                                        {"model": "gemini-3-flash-preview", "usage": None}]}),     # no tokens
        (date(2026, 11, 20), {"calls": [_call("nvidia/nemotron-3-ultra-550b-a55b:free", 5, 5),    # free
                                        _call("some-new-model", 10, 10)]}),                        # no price
        (date(2026, 10, 30), {"calls": []}),
    ]
    nov, octo = council_costs(rows)
    assert nov == {"month": "2026-11", "usd": 1.25, "calls": 5, "unpriced": 2}
    assert octo == {"month": "2026-10", "usd": 0.0, "calls": 0, "unpriced": 0}
