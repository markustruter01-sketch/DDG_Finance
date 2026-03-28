/**
 * Shell.tsx — AlgoEdge SaaS Platform layout wrapper
 *
 * Provides the persistent frame for every page:
 *   [Dev Mode Banner] ← only when DEV_MODE=true
 *   [Navbar]
 *   [Page content]   ← {children}
 *
 * The shell owns the dark background and sets the base font/color context.
 * All pages render inside <main> without worrying about global chrome.
 */

import { useSaasConfig } from "@/hooks/use-saas-config";
import Navbar from "./Navbar";
import DevModeBanner from "./DevModeBanner";

interface ShellProps {
  children: React.ReactNode;
}

export default function Shell({ children }: ShellProps) {
  const { data: config } = useSaasConfig();

  return (
    <div className="min-h-screen flex flex-col bg-zinc-950 text-zinc-100 antialiased">
      {/* Dev mode amber banner — shown only when flag is active */}
      {config?.dev_mode && <DevModeBanner />}

      {/* Persistent navigation */}
      <Navbar />

      {/* Page content area */}
      <main className="flex-1 w-full">
        {children}
      </main>

      {/* Minimal footer */}
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
