---
name: NYSE validation calendar
description: Equity-history integrity checks must account for exchange closures, including one-off market holidays.
---

Equity daily-bar integrity checks should compare against an exchange calendar, not a Monday-to-Friday calendar or a strict January 1 first-date requirement. Good Friday and one-off closures such as the 2025 national day of mourning can otherwise appear as false missing-data failures.

**Why:** Yahoo GLD/SLV history had clean data but initially flagged known NYSE closures as unexplained gaps.

**How to apply:** For US equity validation windows, allow weekends, standard NYSE holidays, Good Friday, and documented exceptional closures; still fail closed on dates missing beyond that calendar.