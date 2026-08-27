---
name: Pause-state fail closed
description: Safety rule for bots whose identifiers are being migrated between runner profiles and canonical database rows.
---

The runner must enforce the static strategy flag, module flag, and canonical database pause flag, failing closed when any source says paused or the sources disagree. During identifier migrations, create explicit paused rows for both the canonical ID and the legacy alias so direct database inspection cannot show an unpaused alias.

**Why:** A legacy alias can resolve to a canonical database row while the runner still loads its old profile, allowing the platform and strategy host to report different lifecycle states.

**How to apply:** When renaming or reactivating a bot, verify runner registration, static/module flags, alias map, every relevant `bots_state` row, and recent broker/ledger activity before activation. Documentation saying a bot is paused is not activation evidence; production state must agree before any live runner is trusted.