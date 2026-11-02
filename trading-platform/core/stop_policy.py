"""Which positions are stop-free by design (FLEET-V1-LIVE-SPEC.md, section 3).

FLEET-V1's cross-asset sleeve holds 10-year Treasuries, gold, commodities and
the dollar with NO protective stop: its monthly trend call is the exit (Hurst,
Ooi & Pedersen 2017; research_harness/sleeves/xasset_v1.py). Every other
holding on every account keeps its stop.

One definition, read by the kill switch's missing-stop check, the ETF
engine's stop reconciliation and the fleet runtime (sleeve_runtime/fleet_live
.NO_STOP_SYMBOLS must equal TREND_EXIT_LINES; a test checks it).
No imports: this file is loaded by path in tests.
"""

TREND_EXIT_LINES = frozenset({"IEF", "GLD", "DBC", "UUP"})

# Accounts running FLEET-V1-F1 (the only variant with the cross-asset sleeve).
STOP_EXEMPT = {"oracle": TREND_EXIT_LINES}


def stop_exempt(bot_id: str | None, symbol: str | None) -> bool:
    if not bot_id or not symbol:
        return False
    return str(symbol).upper() in STOP_EXEMPT.get(str(bot_id), frozenset())
