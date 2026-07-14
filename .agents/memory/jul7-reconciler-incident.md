---
name: Jul-7 reconciler mass-orphan incident
description: Root cause, self-repair, and fix for the Jul-7 event where Alpaca returned [] and all 5 Active Oracle positions were orphaned.
---

## Rule
The inverse reconciler must not execute orphan-closes when `_open_pos` is empty
but DB has Active rows — empty is a known Alpaca API transient failure mode,
not a real "no positions" state.

## What happened (Jul-7 14:16 UTC)
- `get_positions()` returned `[]` (transient Alpaca API empty response)
- `_inv_broker = set()` → ALL 5 Active trades (ARM/DELL/PANW/MS/MU, date Jun-10,
  age >7d) fell through the `if _inv_ticker in _inv_broker: continue` check
- All 5 orphaned as Closed_Reconciled in 1 second
- Scanner saw `exclude_held(0)` → proposed FTNT/UNH on top of 5 live positions
- **Kill switch tripped** → no new entries placed (saved the account)

## Self-repair (Jul-8)
- Forward reconciler (pipeline.py:959) detected ARM/DELL/MS in Alpaca with
  no Active DB row → created RECON-ARM/DELL/MS-20260708
- PANW: real trailing_stop fired Jul-8 (Closed_Loss -$7.30)
- MU: no RECON row → also legitimately exited before Jul-8
- Current Active: ARM-RECON, DELL-RECON, MS-RECON, BAC (Jul-8), FTNT (Jul-13)

## Fix applied
`pipeline.py` inverse reconciler: `if not _open_pos and _inv_rows: warn + skip`
→ fires high-severity degradation alert instead of orphaning

## Why NOT to restore the Jul-7 rows to Active
- ARM/DELL/MS already have RECON replacement Active rows → duplicates would
  break cap gate (reads 6 instead of 5)
- PANW/MU are genuinely exited → restoring = phantom Active position
- WR ghost exclusion filter (D1) handles metric pollution without data changes
