---
name: External reference source separation
description: Keep externally sourced SPY/SGOV reference bars separate from the ordinary equity research panel.
---

The ordinary equity panel source list and the stored reference-series source list must remain separate. External SPY/SGOV bars may support regime and benchmark calculations, but must not enter universe screening or alter immutable panel provenance.

**Why:** The research ledger was created with Alpaca panel data, while the required complete reference history came from Yahoo; the two vendors produce small but legitimate equity-curve differences even when pooled metrics remain within tolerance.

**How to apply:** Add new vendors only to the reference-series query, preserve the Alpaca-only panel filter, and use an explicit source-aware relative curve tolerance when validating immutable results created from a different reference vendor.

For the recovered Helium panel, SGOV reference coverage is Yahoo-only from 2020-06-01 through 2026-07-31 (1,550 distinct sessions), leaving 334 SPY reference sessions before SGOV coverage. SGOV idle-capital logic must earn zero when its current or prior bar is unavailable.

**Why:** Treating the pre-coverage period as if SGOV existed would introduce an unverified cash return into the historical comparison.

**How to apply:** Keep the gap explicit in research metadata and reports; do not backfill SGOV returns or mix it into the ordinary equity panel.