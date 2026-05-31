---
name: Bot identity canonical set
description: bot-identity.ts has exactly 4 entries after Phase 2 cleanup. All old Kraken aliases removed.
---

## Rule
`src/lib/bot-identity.ts` contains exactly 4 canonical bot identities:
- `oracle` — 🔮 Oracle
- `spy_qqq_trend` — 📈 SPY/QQQ Trend
- `jerome_macro` — 🏛️ Jerome
- `buck_futures` — 🐂 Buck Futures

All other IDs fall through to a safe fallback `{ canonicalId: id, displayName: id, icon: "🤖" }`.

**Why:** Legacy aliases (davy-jones, blackbeard, bot2_spy_qqq) caused confusion. Removing them makes dead-code references obvious immediately (they fall to the robot emoji fallback instead of silently looking valid).

**How to apply:**
- When adding a new bot, add it here first (both as the canonical entry and in STATIC_BOTS in StreamingBotsScreen.tsx, BOT_META in StreamingPerformanceScreen.tsx, and botRuntimeByRegistryId in StreamingBotsScreen.tsx).
- `getBotIdentity(id)` is the only identity lookup — never hardcode display names or icons elsewhere.
