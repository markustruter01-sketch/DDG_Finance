---
name: Bot 3 plan history source
description: Production Neon has Bot 3 price-table schemas but no rows; live planning needs explicit-range Alpaca daily bars.
---

For Bot 3 live planning, production Neon contains the historical-price table schemas but currently has no rows in the crypto or inflation-hedge tables. The 60-observation inverse-volatility calculation must therefore use read-only Alpaca daily bars with an explicit historical date range; development data must not be substituted silently.

**Why:** Alpaca’s default-end history request returned incomplete data, while an explicit range returned sufficient bars for all four assets.

**How to apply:** Request a bounded range, take the latest 61 daily observations per asset, verify counts before calculating, and label the source clearly in the audit output.