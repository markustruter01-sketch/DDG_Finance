import axios from "axios";
import { useDocumentVisibility } from "@/hooks/use-visibility";

export const BASE = import.meta.env.VITE_API_BASE_URL || "/trading-api";
const TRADING_API_SECRET = import.meta.env.VITE_TRADING_API_SECRET || "";

export const api = axios.create({
  baseURL: BASE,
  headers: TRADING_API_SECRET
    ? { "X-Trading-API-Secret": TRADING_API_SECRET }
    : undefined,
});

export function useVisibleInterval(ms: number): number | false {
  const visible = useDocumentVisibility();
  return visible ? ms : false;
}
