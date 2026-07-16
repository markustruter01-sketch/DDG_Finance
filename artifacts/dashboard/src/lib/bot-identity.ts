// Single source of truth for bot identity (icon + display name + canonical ID).
// Keys are canonical bot_ids returned by /fleet/equity.

export interface BotIdentity {
  canonicalId: string;
  displayName: string;
  icon: string;
}

const IDENTITY_MAP: Record<string, BotIdentity> = {
  "oracle":        { canonicalId: "oracle",        displayName: "Larry (Oracle)",    icon: "🔮" },
  "spy_qqq_trend": { canonicalId: "spy_qqq_trend", displayName: "Moe (SPY/QQQ)",    icon: "📈" },
  "jerome_macro":  { canonicalId: "jerome_macro",  displayName: "Curly (Jerome)",   icon: "🏛️" },
  "buck_futures":  { canonicalId: "buck_futures",  displayName: "Curly Jr (Buck)",  icon: "🐂" },
};

export function getBotIdentity(id: string): BotIdentity {
  return IDENTITY_MAP[id] ?? {
    canonicalId: id,
    displayName: id,
    icon: "🤖",
  };
}
