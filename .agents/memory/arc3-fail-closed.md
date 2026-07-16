---
name: ARC 3 fail-closed safety pattern
description: Design rule and implementation details for Bucket-C silent failure fixes. Reference before touching any safety-check exception handler.
---

## Rule
Every safety check **fails CLOSED** (toward not-trading / pausing / halting).
Capital-risk alerts use `alert_critical()` (direct webhook), never routed through
the degradation tracker — the alert must fire even when the tracker is down.

**Why:** The original code had `except Exception: return False` in 5 safety guards
and unchecked `close_position()` return values, meaning broker/DB failures silently
permitted trading to continue or closed positions went unconfirmed.

## alert_critical() — canonical path
`trading-platform/notifications/discord.py:alert_critical(title, description, fields=None)`
- Wraps `_send_async()` with a COLOR_RED embed
- No dependency on degradation tracker
- Called inside `try/except` at every call site so a bad webhook can't kill the caller

## Individual fixes (all active as of Jul-16)

| Fix | File | Old behaviour | New behaviour |
|-----|------|---------------|---------------|
| C-1 | kraken-bot/bot2_spy_qqq.py | `close_position()` return ignored → `record_close` always called | `_safe_close()` helper: checks return; if False → Discord + degradation(critical) + skip record_close; DB stays Active for retry |
| C-2 | core/fleet_halt.py | `except → return False` (fail-open) | cold cache → `return True`; warm cache → return cached value; both log WARNING |
| C-3 | execution/kill_switch.py | `except → return False` + "trading will continue" | `except → return True` (fail-TRIPPED) + direct Discord alert |
| C-4 | core/bot_drawdown_guard.py | `except → return _ok()` (fail-open) | `except → {should_pause: True, reason: "drawdown_guard_unavailable"}` |
| C-5 | core/market_state.py | `except: return False` | `except → return True` (fail-CLOSED, treats as CRISIS) |
| C-6 | execution/oracle_exit_manager.py | close failure → `continue` silently | close failure → Discord alert + record_degradation(critical), each in own try/except |

## Self-recovery
C-2/C-3/C-4/C-5 all recompute fresh each call — no sticky state in the except
handler. A transient DB blip clears automatically next cycle when DB is up again.

## How to apply
- Any new safety guard exception handler: default to return the "blocked" value (True for is_halted/is_crisis/kill_switch, should_pause=True for drawdown guard).
- Any close/order submission failure: call alert_critical() directly, wrap in its own try/except, then call record_degradation() in a second independent try/except.
- Never call alert_critical() inside the degradation tracker — circular dependency risk.
