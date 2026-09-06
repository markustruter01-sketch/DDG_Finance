---
name: Bot 3 production data gap
description: Bot 3's live inverse-volatility rebalance requires complete historical closes for BTC, ETH, GLD, and SLV.
---

Bot 3's planner cannot safely derive target weights unless its configured Yahoo-source price tables contain at least 61 closes for every asset in the four-symbol universe. Missing history must fail closed; do not substitute the nominal 25% weight or manually rebalance metals.

**Why:** The configured targets are inverse-volatility weights with floor/cap constraints, so a missing crypto series changes the relative weights of GLD and SLV. A placeholder could cause an incorrect live buy while leaving the portfolio outside its intended allocation.

**How to apply:** Before any Bot 3 metal cancel/replace or buy, verify complete production history for BTC, ETH, GLD, and SLV, verify the US equity session is open, then compute targets from the source function. If either gate fails, preserve existing stops and report the blocker.