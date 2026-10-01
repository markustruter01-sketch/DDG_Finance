export interface BotIdentity {
  canonicalId: string;
  displayName: string;
  shortName: string;
  icon: string;
}

const identities: Record<string, BotIdentity> = {
  oracle: { canonicalId: "oracle", displayName: "Asia-Pacific", shortName: "Asia", icon: "🌏" },
  spy_qqq_trend: { canonicalId: "spy_qqq_trend", displayName: "US Core", shortName: "US Core", icon: "📈" },
  jerome_macro: { canonicalId: "jerome_macro", displayName: "Emerging Markets", shortName: "EM", icon: "🌎" },
};

export function getBotIdentity(id: string): BotIdentity {
  return identities[id] ?? { canonicalId: id, displayName: id, shortName: id, icon: "🤖" };
}

export function getAttributedBotIdentity(id?: string | null): BotIdentity {
  const normalized = typeof id === "string" ? id.trim() : "";
  return identities[normalized] ?? {
    canonicalId: normalized || "unattributed",
    displayName: normalized ? `Unknown bot (${normalized})` : "Unattributed",
    shortName: "Unknown",
    icon: "?",
  };
}