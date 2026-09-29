// Single source of truth for bot identity (icon + display name + canonical ID).
// Keys are canonical bot_ids returned by /fleet/equity.

export interface BotIdentity {
  canonicalId: string;
  displayName: string; // Full label: "Moe (SPY/QQQ)"
  shortName:   string; // Compact label for tight spaces: "Moe"
  icon:        string;
}

const IDENTITY_MAP: Record<string, BotIdentity> = {
  "oracle":        { canonicalId: "oracle",        displayName: "Asia-Pacific",     shortName: "Asia",     icon: "🌏" },
  "spy_qqq_trend": { canonicalId: "spy_qqq_trend", displayName: "US Core",          shortName: "US Core",  icon: "📈" },
  "jerome_macro":  { canonicalId: "jerome_macro",  displayName: "Emerging Markets", shortName: "EM",   icon: "🌎" },
  // buck_futures retired (Stage 5 merge 2026-08-11) — merged into jerome_macro EM bot
  // Entry kept so legacy DB references render gracefully rather than falling back to 🤖
  "buck_futures":  { canonicalId: "buck_futures",  displayName: "Frontier (Retired)", shortName: "Retired", icon: "🌍" },
};

export function getBotIdentity(id: string): BotIdentity {
  return IDENTITY_MAP[id] ?? {
    canonicalId: id,
    displayName: id,
    shortName:   id,
    icon: "🤖",
  };
}

/**
 * Resolve only explicit canonical IDs for data attribution. Unlike
 * getBotIdentity(), this never treats a missing or unknown ID as a valid bot.
 */
export function getAttributedBotIdentity(id?: string | null): BotIdentity {
  const normalized = typeof id === "string" ? id.trim() : "";
  const identity = normalized ? IDENTITY_MAP[normalized] : undefined;
  if (identity) return identity;

  return {
    canonicalId: normalized || "unattributed",
    displayName: normalized ? `Unknown bot (${normalized})` : "Unattributed",
    shortName: "Unknown",
    icon: "?",
  };
}
