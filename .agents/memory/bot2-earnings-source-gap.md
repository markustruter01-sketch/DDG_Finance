---
name: Bot 2 earnings source gap
description: Known completeness issue in the Alpha Vantage earnings history used by the development-only Bot 2 validation.
---

The Alpha Vantage earnings feed currently has no Costco event between the 2020-03-05 and 2020-09-24 reported dates. Treat this as an incomplete quarterly history and stop the split-sample validation; do not fabricate an event or silently remove COST from the locked universe.

**Why:** The validation runbook requires a hard stop on missing quarters so the 2018–2022 selection sample cannot be biased by source omissions.

**How to apply:** Before registering or computing an experiment result, run the per-symbol earnings-gap gate and resolve the source data with an independent authoritative record before rerunning.