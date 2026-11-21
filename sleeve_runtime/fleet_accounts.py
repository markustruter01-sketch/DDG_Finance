"""Which FLEET-V1 variant runs on which Alpaca account: the one place.

Pure data, no imports: the live runtime (sleeve_runtime/fleet_live.py), the
twins (trading-platform/twins/config.py), the routes and the checks all read
it, and the twins may not import the order path.

A variant is (share of the account in the equity core, share in the
cross-asset sleeve):
  FLEET-V1-F1  0.65 / 0.35  Atlas (oracle), since 2 Nov 2026
  FLEET-V1-C1  1.00 / 0.00  Atlas V2 (jerome_macro), since 3 Nov 2026
  FLEET-V1-X1  0.00 / 1.00  the cross-asset trend rule alone: 10-year
               Treasuries, gold, commodities and the dollar (xasset_v1),
               no shares (roadmap v2, V2-03)

🔴 At the lock (12-13 Dec 2026), Markus's decision D2 = B (22 Nov 2026 06:22
Brisbane): jerome_macro changes from FLEET-V1-C1 to FLEET-V1-X1. That is a
one-line change below, published with the US market closed, after Markus's
yes on the day. Its first cycle sells the share core (SPY, QQQ, SSO, QLD)
and buys the cross-asset lines, which carry no stop by design. The tests in
sleeve_runtime/tests/test_fleet_live.py rehearse that switch on a fake broker.

The same lock pull request also changes, or a test fails
(trading-platform/tests/test_fleet_accounts.py): jerome_macro's strategy_label
in trading-platform/core/bot_registry.py, its strategy_type and strategy_label
in kraken-bot/config.py, and its instrument list in trading-platform/core/
ddg_push.py. Separately at the lock: RUN_START in trading-platform/core/
fleet_capital.py restarts once, and the twins start their next VERSION.
Stop exemptions for the cross-asset lines are already in place for this
account (trading-platform/core/stop_policy.py).
"""

SPLITS = {
    "FLEET-V1-F1": (0.65, 0.35),
    "FLEET-V1-C1": (1.00, 0.00),
    "FLEET-V1-X1": (0.00, 1.00),
}

ACCOUNTS = {
    "oracle": "FLEET-V1-F1",
    "jerome_macro": "FLEET-V1-C1",          # 🔴 -> "FLEET-V1-X1" at the lock (D2 = B)
}

# Plain words for screens and reports, one per variant.
LABELS = {
    "FLEET-V1-F1": "FLEET-V1-F1: 65% geared S&P/Nasdaq trend core + 35% cross-asset trend",
    "FLEET-V1-C1": "FLEET-V1-C1: geared S&P/Nasdaq trend core (F1 without the cross-asset sleeve)",
    "FLEET-V1-X1": "FLEET-V1-X1: trend on bonds, gold, commodities and the dollar (no shares)",
}


def state_key(registration: str) -> str:
    """bots_state.metadata key of a variant: FLEET-V1-X1 -> fleet_v1_x1."""
    return registration.lower().replace("-", "_")
