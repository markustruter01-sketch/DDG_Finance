/**
 * DevModeBanner.tsx
 * Shown at the very top of every page when DEV_MODE=true.
 * Visually distinguishes the dev environment from production and
 * provides a one-click toggle to simulate production mode.
 */

import { AlertTriangle } from "lucide-react";
import { useDevModeToggle } from "@/hooks/use-saas-config";

export default function DevModeBanner() {
  const toggle = useDevModeToggle();

  return (
    <div className="w-full bg-amber-400 text-amber-950 text-xs font-semibold flex items-center justify-center gap-2 px-4 py-1.5 select-none">
      <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
      <span>DEV MODE ACTIVE — authentication is bypassed. Not for public access.</span>
      <button
        onClick={() => toggle.mutate()}
        disabled={toggle.isPending}
        className="ml-3 rounded bg-amber-950/20 hover:bg-amber-950/30 px-2 py-0.5 text-amber-950 font-bold transition-colors disabled:opacity-50"
      >
        {toggle.isPending ? "toggling…" : "disable dev mode"}
      </button>
    </div>
  );
}
