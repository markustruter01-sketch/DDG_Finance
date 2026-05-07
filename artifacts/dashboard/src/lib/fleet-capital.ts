import type { FleetEquityData } from "@/hooks/use-trading";

const META_KEYS = new Set(["fleet_total", "generated_at", "errors"]);

const DEFAULT_STARTING = 900_000;
const DEFAULT_BOT_COUNT = 9;

export function getFleetStartingCapital(data: FleetEquityData | undefined): number {
  return data?.fleet_total?.starting ?? DEFAULT_STARTING;
}

export function getFleetBotCount(data: FleetEquityData | undefined): number {
  if (!data) return DEFAULT_BOT_COUNT;
  return Object.keys(data).filter(k => !META_KEYS.has(k)).length;
}

export function formatCapitalShort(amount: number): string {
  if (amount >= 1_000_000) return `$${(amount / 1_000_000).toFixed(1)}M`;
  return `$${Math.round(amount / 1_000)}k`;
}

export function formatCapitalFull(amount: number): string {
  return `$${amount.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}
