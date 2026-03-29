/**
 * Navbar.tsx — AlgoEdge top navigation bar
 *
 * Structure:
 *   LEFT   — AlgoEdge logo mark + wordmark
 *   CENTER — nav links (Home, Dashboard, Settings) with active highlighting
 *   RIGHT  — API status dot · version chip · user chip · DEV badge
 */

import { Link, useLocation } from "wouter";
import { Activity, Terminal } from "lucide-react";
import { useSaasConfig } from "@/hooks/use-saas-config";
import { useAuth } from "@/context/AuthContext";

const NAV_LINKS = [
  { label: "Home",      href: "/" },
  { label: "Dashboard", href: "/dashboard" },
  { label: "Pricing",   href: "/pricing" },
  { label: "Settings",  href: "/settings" },
];

export default function Navbar() {
  const [location] = useLocation();
  const { data: config, isSuccess } = useSaasConfig();
  const { user } = useAuth();

  return (
    <nav className="h-14 w-full border-b border-zinc-800 bg-zinc-950 flex items-center px-6 gap-6 shrink-0">
      {/* Logo */}
      <Link href="/" className="flex items-center gap-2 select-none mr-4">
        <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-indigo-600 text-white text-xs font-black tracking-tight">
          AE
        </span>
        <span className="text-zinc-100 font-semibold text-sm tracking-wide hidden sm:block">
          AlgoEdge
        </span>
      </Link>

      {/* Nav links */}
      <div className="flex items-center gap-1">
        {NAV_LINKS.map(({ label, href }) => {
          const isActive =
            href === "/" ? location === "/" : location.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={[
                "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                isActive
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60",
              ].join(" ")}
            >
              {label}
            </Link>
          );
        })}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Right-side status chips */}
      <div className="flex items-center gap-3">
        {/* API liveness dot */}
        <div className="flex items-center gap-1.5">
          <span
            className={[
              "w-1.5 h-1.5 rounded-full",
              isSuccess ? "bg-emerald-400" : "bg-zinc-600",
            ].join(" ")}
          />
          <span className="text-zinc-500 text-xs hidden md:block">
            {isSuccess ? "API online" : "connecting…"}
          </span>
        </div>

        {/* Version chip */}
        {config && (
          <span className="hidden md:inline-flex items-center gap-1 rounded-full border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-zinc-500 text-xs">
            <Activity className="w-3 h-3" />
            v{config.version}
          </span>
        )}

        {/* User chip */}
        {user && (
          <div className="flex items-center gap-2 rounded-full border border-zinc-700/60 bg-zinc-900 pl-1.5 pr-3 py-1">
            {/* Avatar — initials or Terminal icon for dev user */}
            <span
              className={[
                "inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold shrink-0",
                user.dev_mode
                  ? "bg-amber-400/20 text-amber-400"
                  : "bg-indigo-600/30 text-indigo-400",
              ].join(" ")}
            >
              {user.dev_mode ? (
                <Terminal className="w-3 h-3" />
              ) : (
                user.name.charAt(0).toUpperCase()
              )}
            </span>
            <span className="text-zinc-300 text-xs font-medium leading-none hidden sm:block">
              {user.name}
            </span>
          </div>
        )}

        {/* DEV MODE badge */}
        {config?.dev_mode && (
          <span className="inline-flex items-center rounded-full bg-amber-400/15 border border-amber-400/30 px-2 py-0.5 text-amber-400 text-xs font-semibold tracking-wide">
            DEV
          </span>
        )}
      </div>
    </nav>
  );
}
