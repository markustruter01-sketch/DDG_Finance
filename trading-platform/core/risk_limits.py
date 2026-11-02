"""Fleet drawdown limits: the one definition used by the risk governor, the
kill switch and the FLEET-V1 account governor.

FLEET-V1-LIVE-SPEC.md section 4 (owner's decision, 2 Nov 2026): the limits
are ENFORCED.
- SOFT_DRAWDOWN: the risk governor refuses new risk (buys) above this, and
  each FLEET-V1 account halves every target (sleeve_runtime/fleet_live.py)
  until its equity is back to 95% of its high-water mark.
- HARD_DRAWDOWN: the kill switch trips (latch, pause every bot, cancel
  non-stop orders, keep protective stops) on the fleet's drawdown, and each
  FLEET-V1 account sells to cash and halts until the owner clears it.
Integrity checks (missing stops, ledger mismatches, negative cash, unknown
equity, a latched switch) are not drawdown limits and act as before.

History: 10%/15% (low risk), then 20%/25% record-only (medium, 23 Oct 2026).
"""

RISK_PROFILE = "fleet_v1"
SOFT_DRAWDOWN = 0.15
HARD_DRAWDOWN = 0.22
ENFORCE_DRAWDOWN_LIMITS = True

WOULD_HAVE = {
    "governor_soft": "refuse every new buy (sells and protective stops continue)",
    "kill_switch_hard": "trip: latch, pause every bot, cancel non-stop orders, keep protective stops",
}
