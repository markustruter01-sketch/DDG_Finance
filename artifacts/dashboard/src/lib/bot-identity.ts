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
  jerome_macro: "#3DDC97",  // Atlas V2 (was Bullion) · Mint
  forex_ai: "#F2E35C",      // Forex · Yellow (was white, the same as the S&P 500 line: Markus 21 Nov)
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

/** What every screen calls a bot (Markus 21 Nov): its fixed number, then its current name,
 *  e.g. "Bot 1 · Atlas". The back end keeps its permanent ids (oracle, jerome_macro, …);
 *  screens never show them. Renaming a bot = one edit in core/bot_registry.py. */
export function botLabel(entry?: Pick<BotRegistryEntry, "code" | "display_name"> | null, fallback = "Unknown bot"): string {
  if (!entry) return fallback;
  return entry.code ? `${entry.code} · ${entry.display_name}` : entry.display_name;
}

function makeIdentity(id: string, entry?: BotRegistryEntry): BotIdentity {
  return {
    canonicalId: entry?.id ?? id,
    code: entry?.code || "",
    displayName: botLabel(entry, "Unknown bot"),
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

/** id (or old alias) → screen label, plus a helper that swaps raw ids inside server text
 *  (alarm messages, reasons) for labels. */
export function useBotLabels() {
  const { data } = useBotRegistry();
  return useMemo(() => {
    const byId = new Map<string, string>();
    for (const bot of data?.bots ?? []) {
      byId.set(bot.id, botLabel(bot));
      for (const alias of bot.legacy_aliases ?? []) byId.set(alias, botLabel(bot));
    }
    const ids = [...byId.keys()].sort((a, b) => b.length - a.length).map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const re = ids.length ? new RegExp(`(?<![A-Za-z0-9_])(${ids.join("|")})(?![A-Za-z0-9_])`, "g") : null;
    return {
      label: (id: string) => byId.get(id) ?? id,
      has: (id: string) => byId.has(id),
      humanize: (text: string) => (re ? text.replace(re, (m) => byId.get(m) ?? m) : text),
    };
  }, [data?.bots]);
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
