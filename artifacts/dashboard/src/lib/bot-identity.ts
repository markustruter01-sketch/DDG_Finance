// Bot labels come from the trading API registry; this module only resolves the
// API data and supplies a non-label icon fallback for unknown identities.
import { useMemo } from "react";
import { useBotRegistry, type BotRegistryEntry } from "@/hooks/use-portfolio";

export interface BotIdentity {
  canonicalId: string;
  displayName: string;
  subtitle: string;
  shortName: string;
  icon:        string;
}

function makeIdentity(id: string, entry?: BotRegistryEntry): BotIdentity {
  return {
    canonicalId: entry?.id ?? id,
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
