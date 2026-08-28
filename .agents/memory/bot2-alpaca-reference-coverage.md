---
name: Bot 2 Alpaca reference coverage
description: Alpaca asset metadata and historical-bar coverage limits that affect Bot 2 universe parity.
---

Bot 2's ordinary-equity screen must remain exclusion-based and fail-closed: Alpaca exposes descriptive names but no reliable dedicated ETF/common-stock type, and its bars endpoint may have no 2018-present history for many catalog symbols, including inactive lines. Adjusted-price artifact checks must inspect only the same trailing `min_sessions` window supplied to live screening; older research-only artifacts are not observable by the live caller.

**Why:** Expanded development ingestion can complete successfully while historical parity still fails, and checking a longer stored history than live has creates false research-only exclusions. Treating missing history as passing or silently substituting a ticker blocklist would invalidate the research.

**How to apply:** Keep the local universe gate at STOP until the same calibrated floor and as-of date produce an exact live/research set report after the adjusted-history backfill. The current development calibration is 500 names at a $223,555,361.895 median-dollar-volume floor; do not activate live Bot 2 from the research result alone.