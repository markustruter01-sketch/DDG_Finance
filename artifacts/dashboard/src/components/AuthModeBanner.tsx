import { ShieldAlert } from "lucide-react";
import { useSystemHealth } from "@/hooks/use-platform";

export function AuthModeBanner() {
  const { data } = useSystemHealth();

  if (data?.auth_mode !== "bypass") {
    return null;
  }

  return (
    <div
      role="alert"
      className="fixed left-3 right-3 top-20 z-[10000] flex items-start gap-3 rounded-xl border border-red-400/60 bg-red-950/95 px-4 py-3 text-red-50 shadow-2xl shadow-red-950/40 backdrop-blur sm:left-1/2 sm:right-auto sm:top-3 sm:w-[min(620px,calc(100vw-1.5rem))] sm:-translate-x-1/2"
    >
      <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-red-300" aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-xs font-black uppercase tracking-[0.18em] text-red-200">
          Authentication bypass enabled
        </p>
        <p className="mt-1 text-xs leading-5 text-red-100/90">
          Protected dashboard routes are accessible without Clerk or passkey verification.
          Restore <code className="font-mono text-red-100">TRADING_API_AUTH_MODE=enforced</code>{" "}
          when finished.
        </p>
      </div>
    </div>
  );
}