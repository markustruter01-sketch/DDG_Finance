---
name: Research connection isolation
description: Boundary rule for historical research code and the live application database
---

Research-only modules must use the explicit Helium research connection and must not import the shared application database at module initialization. The research boundary must validate the expected database and fail closed when no explicit or permitted development-only source exists.

**Why:** Import-time shared-pool initialization caused unrelated research runs to probe an invalid application DSN and obscured which database the Strategy Bench was actually using.

**How to apply:** Keep research loaders, gates, and routes behind the dedicated connection module. Treat shared database imports in research dependency graphs as a defect, even when the imported helper is not called.