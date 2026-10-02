---
name: Bot 2 market-data feed access
description: Verified Alpaca market-data entitlements for Bot 2 and how to interpret IEX dry-runs.
---

On 2026-10-02, Bot 2's default SIP bars request returned HTTP 403 for the configured account. The same credentials successfully returned historical bars via Alpaca's IEX feed. An IEX dry-run is not evidence that SIP access works, and its rankings are feed-specific.

**Why:** Silently changing the market-data feed can change the strategy's price history and rankings.

**How to apply:** Before unpausing Bot 2, verify the configured feed has access and run the matching feed for the final dry-run. If SIP remains unavailable and IEX is used for diagnostics, label that output as IEX rather than treating it as SIP-equivalent.