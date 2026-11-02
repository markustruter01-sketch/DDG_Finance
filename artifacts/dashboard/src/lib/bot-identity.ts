// Bot labels come from the trading API registry; this module only resolves the
// API data and supplies a non-label icon fallback for unknown identities.
import { useMemo } from "react";
import { useBotRegistry, type BotRegistryEntry } from "@/hooks/use-portfolio";

/** Each account's colour on every card and chart (brand colours, Markus 31 Oct).
 *  Fixed per account, never by position in a list. Amber is never an account
 *  colour: it only means a loss or a problem. */
export const BOT_COLORS: Record<string, string> = {
  oracle: "#6CC7F0",        // Atlas · Ice
  spy_qqq_trend: "#A78BFA", // Momentum · Violet
  bot2_spy_qqq: "#A78BFA",  // Momentum's older ledger name
  jerome_macro: "#3DDC97",  // Bullion · Mint
  forex_ai: "#FFFFFF",      // Forex · White
};
export const botColor = (id?: string | null) => (id && BOT_COLORS[id]) || "rgba(255,255,255,0.5)";

export interface BotIdentity {
  canonicalId: string;
  code: string;
  displayName: string;
  subtitle: string;
  shortName: string;
  icon:        string;
}

function makeIdentity(id: string, entry?: BotRegistryEntry): BotIdentity {
  return {
    canonicalId: entry?.id ?? id,
    code: entry?.code || id,
    displayName: entry?.display_name ?? id,
    subtitle: entry?.subtitle ?? "",
    shortName: entry?.short_name ?? id,
    icon: entry?.icon ?? "🤖",
  };
}

export function formatBotLabel(identity: BotIdentity): string {
  return identity.subtitle
    ? `${identity.displayName} · ${identity.subtitle}`
    : identity.displayName;
}

export function useBotIdentity() {
  const { data } = useBotRegistry();
  const entriesByIdentity = useMemo(() => {
    const entries = new Map<string, BotRegistryEntry>();
    for (const bot of data?.bots ?? []) {
      entries.set(bot.id, bot);
      for (const alias of bot.legacy_aliases ?? []) entries.set(alias, bot);
    }
    return entries;
  }, [data?.bots]);

  return useMemo(() => {
    const getBotIdentity = (id: string) =>
      makeIdentity(id, entriesByIdentity.get(id));
    const getAttributedBotIdentity = (id?: string | null) => {
      const normalized = typeof id === "string" ? id.trim() : "";
      const entry = normalized ? entriesByIdentity.get(normalized) : undefined;
      return makeIdentity(normalized || "unattributed", entry);
    };
    return { getBotIdentity, getAttributedBotIdentity };
  }, [entriesByIdentity]);
}
