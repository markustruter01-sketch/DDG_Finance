---
name: Alpaca order numeric confirmation
description: Broker order numeric fields may omit trailing zeros, so confirmations must compare numeric values.
---

Alpaca may return an accepted stop price such as `1853.5228741` when the submitted authorized value was `1853.52287410`. Order confirmations must compare parsed numeric values, not raw decimal strings.

**Why:** A raw-string comparison can falsely fail after a broker accepts the order, leaving a staged execution paused between protective-stop replacement and the next operation.

**How to apply:** Parse broker quantities and prices as Decimal values, compare numerically, and preserve the authorized formatted values only for display or submission.