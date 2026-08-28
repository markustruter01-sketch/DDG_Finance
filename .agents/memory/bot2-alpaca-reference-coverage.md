---
name: Bot 2 Alpaca reference coverage
description: Alpaca asset metadata and historical-bar coverage limits that affect Bot 2 universe parity.
---

Bot 2's ordinary-equity screen must remain positive and fail-closed: Alpaca exposes descriptive names but no reliable dedicated ETF/common-stock type, and its bars endpoint may have no 2018-present history for many catalog symbols, including inactive lines.

**Why:** The expanded development ingestion can complete successfully while historical parity still fails; treating missing history as a passing or silently substituting a ticker blocklist would invalidate the research.

**How to apply:** Keep the local universe gate at STOP until a concrete reference-ticker/security-master source (such as Polygon/Massive reference tickers or a licensed equivalent) supplies security type, lineage, and historical coverage.