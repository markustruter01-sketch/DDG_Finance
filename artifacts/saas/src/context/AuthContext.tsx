/**
 * AuthContext.tsx — AlgoEdge authentication context
 *
 * The only source of truth for "who is logged in".
 *
 * Auth flow:
 *   1. AuthProvider mounts → fetches GET /saas-api/auth/me
 *   2a. DEV_MODE=true  → backend returns a mock Dev User (200)
 *       → user is populated; all pages render normally
 *   2b. DEV_MODE=false → backend returns 401 (not authenticated)
 *       → user is null; Shell renders the LoginGate
 *
 * This means:
 *   - Pages never know whether they have a real or mock user — they
 *     just read from useAuth(). The bypass is entirely in the backend.
 *   - Flipping the DEV_MODE toggle forces a re-fetch of /auth/me,
 *     instantly switching between the two states in the UI.
 */

import {
  createContext,
  useContext,
  ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiUrl } from "@/lib/config";

export interface SaasUser {
  id: string;
  name: string;
  email: string;
  role: "developer" | "user" | "admin";
  dev_mode: boolean;
}

interface AuthContextValue {
  user: SaasUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  refetch: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export const AUTH_QUERY_KEY = ["saas-auth-me"] as const;

async function fetchMe(): Promise<SaasUser | null> {
  const res = await fetch(apiUrl("/auth/me"));
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`/auth/me failed: ${res.status}`);
  return res.json();
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();

  const { data: user = null, isLoading } = useQuery<SaasUser | null>({
    queryKey: AUTH_QUERY_KEY,
    queryFn: fetchMe,
    staleTime: 10_000,
    retry: false,
  });

  function refetch() {
    qc.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: user !== null,
        refetch,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
