---
name: ETF broker stop lifecycle
description: Safety rules for broker-native GTC stops around ETF entry, partial exits, and full exits.
---

Every shared-engine ETF entry must persist its position row, arm a broker-native GTC stop after any broker fill, and reconcile the stop at startup. Queued DAY entries need monitoring through the next session as well as cycle-level reconciliation.

Stop ownership is defined by a bot-scoped broker client-order marker. Never adopt or cancel a same-symbol sell order that lacks that marker.

Exit operations must be client-ID fenced: while an owned market exit is open, do not create or replace a stop. Cancel and confirm a protective stop before reducing exposure; re-establish it only after the exit is terminal or canceled. Mark database positions closed only after Alpaca confirms the broker is flat.

**Why:** A database-only stop does not protect broker capital. Unscoped stop reconciliation and asynchronous partial exits can otherwise create overlapping sell orders or remove the only protection from an unfilled position.

**How to apply:** Any strategy that uses AlpacaEtfEngine must call its entry arming and startup reconciliation methods, and use the bot-aware close path. New strategies must not call the generic close method without bot and recorded-stop metadata.