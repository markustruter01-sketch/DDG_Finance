// Maps legacy bot IDs (used in API responses) to canonical display info.
// Source of truth: /trading-api/bot-registry — this is a static fallback
// for components that can't call hooks (non-React files).

export interface BotIdentity {
  canonicalId: string;
  displayName: string;
  icon: string;
}

const IDENTITY_MAP: Record<string, BotIdentity> = {
  "oracle":              { canonicalId: "oracle",             displayName: "Oracle",             icon: "🔮" },
  "spy_qqq_trend":       { canonicalId: "spy_qqq_trend",      displayName: "SPY/QQQ Trend",      icon: "📈" },
  "bot2_spy_qqq":        { canonicalId: "spy_qqq_trend",      displayName: "SPY/QQQ Trend",      icon: "📈" },
  "davy-jones":          { canonicalId: "spy_qqq_trend",      displayName: "SPY/QQQ Trend",      icon: "📈" },
  "jerome_macro":        { canonicalId: "jerome_macro",       displayName: "Jerome",             icon: "🏛️" },
  "blackbeard":          { canonicalId: "jerome_macro",       displayName: "Jerome",             icon: "🏛️" },
  "sector_rotation":     { canonicalId: "sector_rotation",    displayName: "Sector Rotation",    icon: "🔄" },
  "bot4_sector":         { canonicalId: "sector_rotation",    displayName: "Sector Rotation",    icon: "🔄" },
  "calypso":             { canonicalId: "sector_rotation",    displayName: "Sector Rotation",    icon: "🔄" },
  "forex_gump":          { canonicalId: "forex_gump",         displayName: "Forex Gump",         icon: "💱" },
  "navigator":           { canonicalId: "forex_gump",         displayName: "Forex Gump",         icon: "💱" },
  "poseidon_momentum":   { canonicalId: "poseidon_momentum",  displayName: "Poseidon",           icon: "🔱" },
  "poseidon":            { canonicalId: "poseidon_momentum",  displayName: "Poseidon",           icon: "🔱" },
  "kraken_trend":        { canonicalId: "kraken_trend",       displayName: "Kraken Current",     icon: "🌊" },
  "kraken-current":      { canonicalId: "kraken_trend",       displayName: "Kraken Current",     icon: "🌊" },
};

export function getBotIdentity(legacyOrCanonicalId: string): BotIdentity {
  return IDENTITY_MAP[legacyOrCanonicalId] ?? {
    canonicalId: legacyOrCanonicalId,
    displayName: legacyOrCanonicalId,
    icon: "🤖",
  };
}
