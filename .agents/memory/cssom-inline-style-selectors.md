---
name: CSSOM inline-style selectors
description: React inline styles are serialized by the browser before CSS substring selectors inspect them.
---

## Rule
When CSS targets React inline style attributes with `[style*="..."]`, match the browser-serialized value (for example, `rgb(2, 6, 23)` with spaces), not only the source literal (such as `#020617` or `rgba(2,6,23,...)`). Prefer a stable class or data attribute for new selectors.

**Why:** Mobile production-shell styling initially missed some inline backgrounds because selectors matched authored literals while the DOM exposed normalized CSSOM values.

**How to apply:** Inspect rendered style attributes when a substring selector does not match. Keep exact color selectors only as a fallback; use stable semantic selectors for new styling.