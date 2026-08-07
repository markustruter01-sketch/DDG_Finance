// Single source of truth for bot identity (icon + display name + canonical ID).
// Keys are canonical bot_ids returned by /fleet/equity.

export interface BotIdentity {
  canonicalId: string;
  displayName: string; // Full label: "Moe (SPY/QQQ)"
  shortName:   string; // Compact label for tight spaces: "Moe"
  icon:        string;
}

const IDENTITY_MAP: Record<string, BotIdentity> = {
  "oracle":        { canonicalId: "oracle",        displayName: "Larry (Oracle)",   shortName: "Larry",    icon: "🔮" },
  "spy_qqq_trend": { canonicalId: "spy_qqq_trend", displayName: "Moe (SPY/QQQ)",   shortName: "Moe",      icon: "📈" },
  "jerome_macro":  { canonicalId: "jerome_macro",  displayName: "Latin America",  shortName: "LatAm",    icon: "🌎" },
  "buck_futures":  { canonicalId: "buck_futures",  displayName: "Curly Jr (Buck)", shortName: "Curly Jr", icon: "🐂" },
};

export function getBotIdentity(id: string): BotIdentity {
  return IDENTITY_MAP[id] ?? {
    canonicalId: id,
    displayName: id,
    shortName:   id,
    icon: "🤖",
  };
}
