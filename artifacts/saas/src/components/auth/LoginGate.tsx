/**
 * LoginGate.tsx
 * Shown when the user is not authenticated (DEV_MODE=false or future real auth).
 *
 * In the current build stage, real login/signup is not yet implemented.
 * The gate offers a quick "Enable Dev Mode" escape hatch so developers
 * can get back into the app without touching the server.
 *
 * Stage 4 will replace the placeholder CTA with real login/signup forms.
 */

import { useState } from "react";
import { LogIn, Terminal, Loader2 } from "lucide-react";
import { apiUrl } from "@/lib/config";
import { useAuth } from "@/context/AuthContext";

export default function LoginGate() {
  const { refetch } = useAuth();
  const [enabling, setEnabling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleEnableDev() {
    setEnabling(true);
    setError(null);
    try {
      const res = await fetch(apiUrl("/dev-mode/toggle"), { method: "POST" });
      if (!res.ok) throw new Error("Toggle request failed");
      const data = await res.json();
      if (!data.dev_mode) {
        // Toggled off when it was already off — toggle again to enable
        await fetch(apiUrl("/dev-mode/toggle"), { method: "POST" });
      }
      refetch();
    } catch (e) {
      setError("Could not reach the API. Is the server running?");
    } finally {
      setEnabling(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-zinc-950 px-6">
      {/* Logo */}
      <div className="flex items-center gap-3 mb-10 select-none">
        <span className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-indigo-600 text-white text-sm font-black tracking-tight">
          AE
        </span>
        <span className="text-zinc-100 font-semibold text-xl tracking-wide">
          AlgoEdge
        </span>
      </div>

      {/* Card */}
      <div className="w-full max-w-sm rounded-2xl border border-zinc-800 bg-zinc-900 p-8 flex flex-col gap-6">
        {/* Icon + heading */}
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-zinc-800 border border-zinc-700">
            <LogIn className="w-5 h-5 text-zinc-400" />
          </div>
          <div>
            <h1 className="text-zinc-100 font-semibold text-lg">
              Authentication Required
            </h1>
            <p className="mt-1 text-zinc-500 text-sm leading-relaxed">
              Login and signup are coming in Stage 4.
              In the meantime, enable Dev Mode to access the platform.
            </p>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-zinc-800" />

        {/* Stage 4 placeholder CTA */}
        <button
          disabled
          className="w-full rounded-lg bg-indigo-600/30 border border-indigo-500/20 py-2.5 text-indigo-400 text-sm font-medium cursor-not-allowed opacity-60"
        >
          Sign in with email — coming Stage 4
        </button>

        {/* Dev mode escape hatch */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <div className="flex-1 border-t border-zinc-800" />
            <span className="text-zinc-600 text-xs">or</span>
            <div className="flex-1 border-t border-zinc-800" />
          </div>
          <button
            onClick={handleEnableDev}
            disabled={enabling}
            className="w-full flex items-center justify-center gap-2 rounded-lg border border-amber-400/25 bg-amber-400/8 hover:bg-amber-400/15 py-2.5 text-amber-400 text-sm font-medium transition-colors disabled:opacity-50"
          >
            {enabling ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Terminal className="w-4 h-4" />
            )}
            {enabling ? "Enabling…" : "Enable Dev Mode"}
          </button>

          {error && (
            <p className="text-red-400 text-xs text-center">{error}</p>
          )}
        </div>
      </div>

      {/* Footer note */}
      <p className="mt-6 text-zinc-700 text-xs text-center max-w-xs">
        Dev Mode bypasses authentication for local development only.
        Never expose this button in production.
      </p>
    </div>
  );
}
