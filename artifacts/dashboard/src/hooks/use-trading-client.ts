import axios from "axios";
import { useDocumentVisibility } from "@/hooks/use-visibility";

export const BASE = import.meta.env.VITE_API_BASE_URL || "/trading-api";

export const api = axios.create({
  baseURL: BASE,
  withCredentials: true,
});

export function useVisibleInterval(ms: number): number | false {
  const visible = useDocumentVisibility();
  return visible ? ms : false;
}
