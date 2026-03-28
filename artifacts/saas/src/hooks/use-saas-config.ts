/**
 * use-saas-config.ts
 * React Query hook for /saas-api/config
 * Consumed by the Shell and Navbar to read DEV_MODE + platform settings.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiUrl } from "@/lib/config";

export interface SaasConfig {
  version: string;
  dev_mode: boolean;
  auth_required: boolean;
  supported_exchanges: string[];
  risk_model: string;
}

const CONFIG_KEY = ["saas-config"] as const;

async function fetchConfig(): Promise<SaasConfig> {
  const res = await fetch(apiUrl("/config"));
  if (!res.ok) throw new Error(`Config fetch failed: ${res.status}`);
  return res.json();
}

async function toggleDevMode(): Promise<SaasConfig> {
  const res = await fetch(apiUrl("/dev-mode/toggle"), { method: "POST" });
  if (!res.ok) throw new Error(`Toggle failed: ${res.status}`);
  return res.json();
}

export function useSaasConfig() {
  return useQuery<SaasConfig>({
    queryKey: CONFIG_KEY,
    queryFn: fetchConfig,
    staleTime: 15_000,
    retry: 2,
  });
}

export function useDevModeToggle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: toggleDevMode,
    onSuccess: (data) => {
      qc.setQueryData(CONFIG_KEY, data);
    },
  });
}
