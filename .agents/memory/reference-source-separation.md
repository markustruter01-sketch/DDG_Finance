---
name: External reference source separation
description: Keep externally sourced SPY/SGOV reference bars separate from the ordinary equity research panel.
---

The ordinary equity panel source list and the stored reference-series source list must remain separate. External SPY/SGOV bars may support regime and benchmark calculations, but must not enter universe screening or alter immutable panel provenance.

**Why:** The research ledger was created with Alpaca panel data, while the required complete reference history came from Yahoo; the two vendors produce small but legitimate equity-curve differences even when pooled metrics remain within tolerance.

**How to apply:** Add new vendors only to the reference-series query, preserve the Alpaca-only panel filter, and use an explicit source-aware relative curve tolerance when validating immutable results created from a different reference vendor.