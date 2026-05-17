import type { FleetEquityData, BotRegistryResponse } from "@/hooks/use-trading";

const META_KEYS = new Set(["fleet_total", "generated_at", "errors"]);

const DEFAULT_STARTING = 800_000;
const DEFAULT_BOT_COUNT = 8;

export function getFleetStartingCapital(
  registry?: BotRegistryResponse,
  fleetEq?: FleetEquityData
): number {
  if (registry) return registry.fleet_starting_capital;
  if (fleetEq?.fleet_total?.starting) return fleetEq.fleet_total.starting;
  return DEFAULT_STARTING;
}

export function getFleetBotCount(
  registry?: BotRegistryResponse,
  _fleetEq?: FleetEquityData
): number {
  if (registry) return registry.fleet_bot_count;
  return DEFAULT_BOT_COUNT;
}

export function formatCapitalShort(amount: number): string {
  if (amount >= 1_000_000) return `$${(amount / 1_000_000).toFixed(1)}M`;
  return `$${Math.round(amount / 1_000)}k`;
}

export function formatCapitalFull(amount: number): string {
  return `$${amount.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}
