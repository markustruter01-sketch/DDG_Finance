---
name: Fleet chat prompt interpolation
description: Safely inserting registry-sourced labels into the Fleet Commander system prompt.
---

Keep the Fleet Commander system prompt as a plain triple-quoted string and insert dynamic labels through a unique sentinel followed by `.replace()`.

**Why:** Converting the full prompt to an f-string failed to parse because its literal braces and nested expressions exceed Python's f-string parser limits.

**How to apply:** For future dynamic text in this prompt, preserve the literal template and replace a dedicated marker rather than adding an f-string prefix.