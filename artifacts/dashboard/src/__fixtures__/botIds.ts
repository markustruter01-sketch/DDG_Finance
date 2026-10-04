/**
 * Test fixture only — NOT imported by runtime code.
 *
 * The runtime bot list is derived dynamically from /fleet/equity keys,
 * filtered by stale === false. ACTIVE_BOT_IDS here is used only in tests
 * to assert which bots should be present in fleet equity responses.
 */
export const ACTIVE_BOT_IDS = [
  "oracle",
  "spy_qqq_trend",
  "jerome_macro",
  "forex_ai",
] as const;

export type ActiveBotId = (typeof ACTIVE_BOT_IDS)[number];
