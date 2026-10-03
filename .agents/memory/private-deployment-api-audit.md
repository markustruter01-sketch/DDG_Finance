---
name: Private deployment API audit boundary
description: Limits for reading API routes on this project's private published deployment.
---

**Rule:** Direct requests to the private published API may be redirected by ReplShield before application authentication runs. Do not bypass that gate or weaken TLS; use an approved authenticated inspection path and mark unavailable live API facts as unverified.

**Why:** During a production audit, requests to the deployed API were redirected with HTTP 307 to `__replshield` even when sent with the app's service-authentication header.

**How to apply:** Use production database records and deployment logs for the evidence they provide, but do not present local source or build success as proof of the deployed API response or exact deployed source revision.