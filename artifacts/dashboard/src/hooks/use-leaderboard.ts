// One read of /league/leaderboard for every page (League, Me vs bots, Forex, Home cards).
// Real-account rows are named by the bot label rule (lib/bot-identity: "Bot 1 · Atlas"),
// so a renamed bot changes everywhere from the registry, never from the server's text.
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/hooks/use-trading-client";
import { useBotLabels } from "@/lib/bot-identity";

type Named = { id: string; name?: string; kind?: string };

export function useLeaderboard<B extends { rows: Named[] }>() {
  const q = useQuery({
    queryKey: ["league-leaderboard"],
    queryFn: async () => (await api.get("/league/leaderboard")).data as B,
    refetchInterval: 15 * 60_000,
  });
  const labels = useBotLabels();
  const data = useMemo(() => q.data && {
    ...q.data,
    rows: q.data.rows.map((r) => (r.kind === "real" && labels.has(r.id) ? { ...r, name: labels.label(r.id) } : r)),
  } as B, [q.data, labels]);
  return { ...q, data };
}
