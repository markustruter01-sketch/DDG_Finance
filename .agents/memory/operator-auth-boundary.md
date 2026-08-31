---
name: Operator authentication boundary
description: Browser dashboard access uses Clerk sessions; the trading API keeps a separate internal secret for server probes.
---

The browser authenticates with either a same-origin Clerk recovery/setup session or a server-verified WebAuthn passkey session. The trading API's shared secret is server-to-server only, carried in the internal probe header, and must never be injected into the Vite bundle.

**Why:** The previous browser-shipped secret could be extracted from client assets and replayed against protected trading endpoints.

**How to apply:** Keep dashboard API calls credentialed but header-free; use the internal header only for scheduler or other trusted service probes, reject the legacy browser header, and keep passkey private keys and biometric material on the device.