---
name: Pause-state fail closed
description: Safety rule for bots whose identifiers are being migrated between runner profiles and canonical database rows.
---

The runner must enforce both the static strategy pause flag and the canonical database pause flag, failing closed when either says paused. During identifier migrations, create explicit paused rows for both the canonical ID and the legacy alias so direct database inspection cannot show an unpaused alias.

**Why:** A legacy alias can resolve to a canonical database row while the runner still loads its old profile, allowing the platform and strategy host to report different lifecycle states.

**How to apply:** When renaming a bot, verify runner registration, static profile, alias map, and every relevant `bots_state` row before activation. Never resolve a profile/database mismatch by enabling the strategy during a no-order safety review.