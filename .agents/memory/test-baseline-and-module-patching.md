---
name: Test baseline and module patching
description: Project test-suite baseline and the module-reload patching constraint for budget tests.
---

The project’s tracked Python test suite has a dated baseline in `tests/BASELINE.md`. Tests that dynamically reload a module must patch the exact module object returned by the factory, not a package attribute that may point to a different module instance.

**Why:** Removing a module from `sys.modules` can leave package attributes and class method globals pointing at different module objects, causing misleading configuration-test failures.

**How to apply:** Prefer a stable imported module plus a freshly initialized test instance, or return the module object and patch it directly when testing module-level settings.