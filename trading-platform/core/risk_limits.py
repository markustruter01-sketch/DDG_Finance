"""Fleet drawdown limits: the one definition used by the risk governor, the
kill switch and the record-only log.

Markus (23 Oct 2026): run the fleet at MEDIUM risk. While the fleet is on
paper and practice money, crossing a limit must not stop trading; the platform
records, in risk_limit_shadow, exactly what it would have done instead, so the
spec can be judged and tuned on real behaviour.

- SOFT_DRAWDOWN: the risk governor would refuse new risk (buys) above this.
- HARD_DRAWDOWN: the kill switch would trip (latch, pause every bot, cancel
  non-stop orders, keep protective stops) above this.
- ENFORCE_DRAWDOWN_LIMITS: False = record only. Integrity checks (missing
  stops, ledger mismatches, negative cash, unknown equity, a latched switch)
  are NOT drawdown limits and keep acting as before.

Low risk (the earlier setting) was 10% / 15%. Medium was chosen to match the
~25% worst falls of the tested strategies and of SPY over 2021-2026.
"""

RISK_PROFILE = "medium"
SOFT_DRAWDOWN = 0.20
HARD_DRAWDOWN = 0.25
ENFORCE_DRAWDOWN_LIMITS = False

WOULD_HAVE = {
    "governor_soft": "refuse every new buy (sells and protective stops continue)",
    "kill_switch_hard": "trip: latch, pause every bot, cancel non-stop orders, keep protective stops",
}
