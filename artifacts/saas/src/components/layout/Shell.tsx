/**
 * Shell.tsx — AlgoEdge SaaS Platform layout wrapper
 *
 * Auth-aware layout:
 *   LOADING   → full-screen dark spinner (auth check in progress)
 *   UNAUTHED  → LoginGate (full-page login prompt)
 *   AUTHED    → [Dev Banner?] + Navbar + {children} + Footer
 */

import { useSaasConfig } from "@/hooks/use-saas-config";
import { useAuth } from "@/context/AuthContext";
import Navbar from "./Navbar";
import DevModeBanner from "./DevModeBanner";
import LoginGate from "@/components/auth/LoginGate";
import { Loader2 } from "lucide-react";

interface ShellProps {
  children: React.ReactNode;
}

export default function Shell({ children }: ShellProps) {
  const { data: config } = useSaasConfig();
  const { isLoading, isAuthenticated } = useAuth();

  // ── Auth check in progress ────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-zinc-950">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 text-indigo-400 animate-spin" />
          <span className="text-zinc-600 text-xs tracking-wide">
            Checking session…
          </span>
        </div>
      </div>
    );
  }

  // ── Not authenticated → show login gate ───────────────────────────────────
  if (!isAuthenticated) {
    return <LoginGate />;
  }

  // ── Authenticated → render full shell ─────────────────────────────────────
  return (
    <div className="min-h-screen flex flex-col bg-zinc-950 text-zinc-100 antialiased">
      {config?.dev_mode && <DevModeBanner />}
      <Navbar />
      <main className="flex-1 w-full">{children}</main>
      <footer className="border-t border-zinc-800/60 py-4 px-6 flex items-center justify-between">
        <span className="text-zinc-600 text-xs">
          AlgoEdge &copy; {new Date().getFullYear()}
        </span>
        <span className="text-zinc-700 text-xs font-mono">
          {config ? `v${config.version}` : "…"}
        </span>
      </footer>
    </div>
  );
}
