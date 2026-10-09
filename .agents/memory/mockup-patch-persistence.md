---
name: Mockup patch persistence
description: Verify mockup component files after an interrupted mixed patch.
---

If `apply_patch` disconnects while applying a mixed add/update patch, do not rely on per-file success messages alone. Confirm every expected component file exists and that the preview plugin registered it before treating its route as ready.

**Why:** A disconnected patch left the mockup group stylesheet present while the reported component additions were missing, so the canvas previews had no discoverable components.

**How to apply:** After any interrupted patch, inspect the target files and generated mockup registry before restarting the preview workflow or changing iframe states.
