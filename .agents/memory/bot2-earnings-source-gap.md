---
name: Bot 2 earnings source gap
description: Known completeness issue in the Alpha Vantage earnings history used by the development-only Bot 2 validation.
---

The Alpha Vantage earnings feed has no Costco event between the 2020-03-05 and 2020-09-24 reported dates. The development table now contains one explicitly manual row for the verified 2020-05-28 post-market event, with unknown EPS/surprise fields left null.

**Why:** The validation runbook requires a hard stop on missing quarters so the 2018–2022 selection sample cannot be biased by source omissions, while allowing a verified single-row repair without fabricated fundamentals.

**How to apply:** Before registering or computing an experiment result, run the per-symbol fiscal-quarter gate. Manual rows with unknown surprise are valid for buy-before timing but must be excluded from positive-surprise PEAD.