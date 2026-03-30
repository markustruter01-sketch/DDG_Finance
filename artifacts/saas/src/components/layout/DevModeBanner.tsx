/**
 * DevModeBanner.tsx
 * Shown at the very top of every page when DEV_MODE=true (open-access beta).
 * In v0.1.0 authentication is not yet required — this banner signals that
 * to visitors. When Stage 3 auth is complete, set SAAS_DEV_MODE=false to
 * remove this banner and enforce login.
 */

import { useDevModeToggle } from "@/hooks/use-saas-config";

export default function DevModeBanner() {
  const toggle = useDevModeToggle();

  return (
    <div className="w-full bg-indigo-600 text-white text-xs font-medium flex items-center justify-center gap-2 px-4 py-1.5 select-none">
      <span className="opacity-75">●</span>
      <span>Open Beta — No login required. Full access enabled while authentication is in development.</span>
      <button
        onClick={() => toggle.mutate()}
        disabled={toggle.isPending}
        className="ml-3 rounded bg-white/10 hover:bg-white/20 px-2 py-0.5 text-white font-semibold transition-colors disabled:opacity-50 text-xs"
      >
        {toggle.isPending ? "updating…" : "dismiss"}
      </button>
    </div>
  );
}
