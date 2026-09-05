---
name: Pytest collection roots
description: Pytest testpaths need a nearest-directory configuration when the same suite must collect from both repository root and a project subdirectory.
---

The repository keeps equivalent pytest configurations at the workspace root and
inside `trading-platform` so `pytest --collect-only` reaches both
`trading-platform/tests` and `kraken-bot` from either starting directory.

**Why:** Pytest resolves configured discovery paths relative to the invocation
directory in this layout, even when it reports the workspace root as rootdir;
the root-only configuration therefore omitted `kraken-bot` when started inside
`trading-platform`.

**How to apply:** When adding a test tree outside the current project
directory, verify collection from both the workspace root and that project
directory rather than trusting one `testpaths` setting.