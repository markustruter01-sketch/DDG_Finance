/**
 * Home.tsx — AlgoEdge public landing page
 * Dark, minimalist SaaS landing. No data fetching — fully static.
 */

import { Link } from "wouter";
import { TrendingUp, Shield, Zap, Activity, Clock, BarChart2 } from "lucide-react";

const STATS = [
  { value: "10",      label: "Symbols Monitored" },
  { value: "24/7",    label: "Continuous Operation" },
  { value: "RSI+Z",   label: "Dual Signal Filter" },
  { value: "10%",     label: "Max Risk Per Position" },
];

const FEATURES = [
  {
    icon: Activity,
    title: "Real-Time Signal Detection",
    body: "RSI measures momentum deviation from 50. Z-score measures price deviation from its 20-period mean. Both must align — RSI < 40 and Z-score > 1.0 — before a position is opened. No guesswork.",
  },
  {
    icon: Shield,
    title: "Risk-First Position Sizing",
    body: "Every position is capped at 10% of portfolio equity. Maximum 10 simultaneous positions. The bot never over-concentrates regardless of signal strength. Capital preservation is the primary constraint.",
  },
  {
    icon: Zap,
    title: "1-Click Execution",
    badge: "Stage 5",
    body: "Connect your Kraken API key. When signals fire, execute with one click — or let the system trade autonomously. Your keys stay encrypted and never leave your control.",
  },
];

const SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "ADA", "AVAX", "LINK", "DOT", "ATOM", "LTC"];

export default function Home() {
  return (
    <div className="w-full">
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative w-full px-6 py-24 md:py-32 flex flex-col items-center text-center overflow-hidden">
        {/* Background glow */}
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[400px] bg-indigo-600/10 rounded-full blur-3xl" />
        </div>

        {/* Badge */}
        <div className="relative inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 mb-6">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
          <span className="text-indigo-400 text-xs font-medium tracking-wide">
            Live on Kraken paper trading
          </span>
        </div>

        {/* Heading */}
        <h1 className="relative max-w-3xl text-4xl md:text-6xl font-black tracking-tight leading-tight text-zinc-100">
          Algorithmic Edge,{" "}
          <span className="bg-gradient-to-r from-indigo-400 to-violet-400 bg-clip-text text-transparent">
            Simplified
          </span>
        </h1>

        {/* Subheading */}
        <p className="relative mt-5 max-w-xl text-zinc-400 text-lg md:text-xl leading-relaxed">
          AI-driven mean-reversion signals across 10 crypto markets. Real-time RSI +
          Z-score analysis, operating 24/7. No noise — only high-conviction entries.
        </p>

        {/* CTAs */}
        <div className="relative mt-8 flex items-center gap-3 flex-wrap justify-center">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 px-5 py-2.5 text-white text-sm font-semibold transition-colors"
          >
            <BarChart2 className="w-4 h-4" />
            Open Dashboard
          </Link>
          <Link
            href="/settings"
            className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 px-5 py-2.5 text-zinc-300 text-sm font-semibold transition-colors"
          >
            Connect Exchange →
          </Link>
        </div>
      </section>

      {/* ── Stats ────────────────────────────────────────────────────────── */}
      <section className="w-full border-y border-zinc-800 bg-zinc-900/50">
        <div className="max-w-4xl mx-auto px-6 py-10 grid grid-cols-2 md:grid-cols-4 gap-6">
          {STATS.map(({ value, label }) => (
            <div key={label} className="flex flex-col items-center text-center gap-1">
              <span className="text-2xl md:text-3xl font-black text-zinc-100 tracking-tight">
                {value}
              </span>
              <span className="text-zinc-500 text-xs font-medium uppercase tracking-widest">
                {label}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* ── How it works ─────────────────────────────────────────────────── */}
      <section className="w-full px-6 py-20">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-2xl md:text-3xl font-bold text-zinc-100">
              How It Works
            </h2>
            <p className="mt-2 text-zinc-500 text-sm max-w-md mx-auto">
              Three principles drive every decision the system makes.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {FEATURES.map(({ icon: Icon, title, body, badge }) => (
              <div
                key={title}
                className="relative rounded-2xl border border-zinc-800 bg-zinc-900 p-6 flex flex-col gap-4"
              >
                {badge && (
                  <span className="absolute top-4 right-4 rounded-full bg-indigo-500/15 border border-indigo-500/25 px-2 py-0.5 text-indigo-400 text-xs font-semibold">
                    {badge}
                  </span>
                )}
                <div className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-zinc-800 border border-zinc-700">
                  <Icon className="w-5 h-5 text-indigo-400" />
                </div>
                <div>
                  <h3 className="text-zinc-100 font-semibold">{title}</h3>
                  <p className="mt-2 text-zinc-500 text-sm leading-relaxed">{body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Symbol strip ─────────────────────────────────────────────────── */}
      <section className="w-full border-t border-zinc-800 bg-zinc-900/30 px-6 py-10">
        <div className="max-w-4xl mx-auto">
          <p className="text-center text-zinc-600 text-xs uppercase tracking-widest mb-6 flex items-center justify-center gap-2">
            <Clock className="w-3 h-3" /> Monitored 24/7
          </p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            {SYMBOLS.map((s) => (
              <span
                key={s}
                className="rounded-full border border-zinc-700/60 bg-zinc-900 px-3 py-1.5 text-zinc-400 text-xs font-mono font-semibold"
              >
                {s}/USD
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA footer ───────────────────────────────────────────────────── */}
      <section className="w-full px-6 py-20 flex flex-col items-center text-center">
        <h2 className="text-2xl md:text-3xl font-bold text-zinc-100 max-w-lg">
          Ready to see live signals?
        </h2>
        <p className="mt-3 text-zinc-500 text-sm max-w-sm">
          The dashboard shows real-time data from the running paper trading bot.
          No signup required in dev mode.
        </p>
        <Link
          href="/dashboard"
          className="mt-6 inline-flex items-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 px-6 py-3 text-white text-sm font-semibold transition-colors"
        >
          <TrendingUp className="w-4 h-4" />
          View Live Dashboard
        </Link>
      </section>
    </div>
  );
}
