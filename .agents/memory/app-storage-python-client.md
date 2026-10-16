---
name: App Storage Python client
description: Python authentication and dependency compatibility for Replit App Storage.
---

Use `replit-object-storage` for Python access to App Storage. It authenticates through Replit's sidecar; a bare `google.cloud.storage.Client()` expects ADC and fails in the workspace. The SDK currently depends on `google-cloud-storage<3`.

**Why:** The generic GCS Python client did not find default credentials, while the official Replit SDK worked. Its version constraint conflicts with google-cloud-storage 3.x.

**How to apply:** For Python backup or object tasks, use `replit.object_storage.Client` and keep its compatible GCS dependency range. Verify access by listing only the intended bucket prefix.
