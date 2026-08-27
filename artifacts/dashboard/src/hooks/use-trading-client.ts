import axios from "axios";
import { useDocumentVisibility } from "@/hooks/use-visibility";

export const BASE = import.meta.env.VITE_API_BASE_URL || "/trading-api";
const TRADING_API_SECRET = import.meta.env.VITE_TRADING_API_SECRET || "";

export const api = axios.create({
  baseURL: BASE,
});

// Apply the secret at request time so every request made through this shared
// client carries the same header, including requests that override defaults.
api.interceptors.request.use((config) => {
  if (TRADING_API_SECRET) {
    config.headers.set("X-Trading-API-Secret", TRADING_API_SECRET);
  }
  return config;
});

export function useVisibleInterval(ms: number): number | false {
  const visible = useDocumentVisibility();
  return visible ? ms : false;
}
