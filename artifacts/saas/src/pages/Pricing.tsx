/**
 * Pricing.tsx — AlgoEdge Revenue & Licensing Page
 *
 * Psychology-first pricing design:
 * - Weekly display price (not monthly) to look lower
 * - 4-week vs Annual toggle (annual saves 20%)
 * - Tier 3 "Most Popular" badge anchors to the middle
 * - Feature lists reinforce value, not specs
 *
 * Checkout flow:
 *   click Subscribe → POST /saas-api/stripe/checkout → redirect to Stripe Checkout
 */

import { useState } from "react";
import { Check, Zap, Shield, TrendingUp, Star, Loader2, AlertCircle } from "lucide-react";
import { apiUrl } from "@/lib/config";

// ── Types ─────────────────────────────────────────────────────────────────────

type Tier = "tier1" | "tier2" | "tier3";
type Cycle = "4w" | "annual";

interface TierMeta {
  name:          string;
  display_price: string;
  billing_label: string;
  features:      string[];
  badge?:        string;
  exchange_access: string[];
}

// ── Tier definitions (mirrors backend TIERS) ──────────────────────────────────

const TIER_ORDER: Tier[] = ["tier1", "tier2", "tier3"];

const TIER_ICONS: Record<Tier, React.ReactNode> = {
  tier1: <TrendingUp className="w-5 h-5 text-indigo-400" />,
  tier2: <Shield    className="w-5 h-5 text-violet-400"  />,
  tier3: <Zap       className="w-5 h-5 text-amber-400"   />,
};

const TIER_ACCENT: Record<Tier, string> = {
  tier1: "border-indigo-500/40 bg-indigo-500/5",
  tier2: "border-violet-500/40 bg-violet-500/5",
  tier3: "border-amber-500/50  bg-amber-500/8",
};

const TIER_BTN: Record<Tier, string> = {
  tier1: "bg-indigo-600 hover:bg-indigo-500",
  tier2: "bg-violet-600 hover:bg-violet-500",
  tier3: "bg-amber-500  hover:bg-amber-400  text-zinc-900",
};

// ── Annual price display ───────────────────────────────────────────────────────

const ANNUAL_WEEKLY: Record<Tier, string> = {
  tier1: "$3.99 / week",
  tier2: "$7.99 / week",
  tier3: "$10.38 / week",
};

const ANNUAL_BILLED: Record<Tier, string> = {
  tier1: "Billed upfront as $207.58 / year",
  tier2: "Billed upfront as $415.16 / year",
  tier3: "Billed upfront as $539.58 / year",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function CycleToggle({
  cycle, onChange,
}: { cycle: Cycle; onChange: (c: Cycle) => void }) {
  return (
    <div className="flex items-center gap-3 select-none">
      <button
        onClick={() => onChange("4w")}
        className={[
          "text-sm font-medium transition-colors",
          cycle === "4w" ? "text-zinc-100" : "text-zinc-500",
        ].join(" ")}
      >
        Every 4 Weeks
      </button>

      {/* Toggle pill */}
      <div
        className="relative w-10 h-5 rounded-full bg-zinc-700 cursor-pointer flex items-center"
        onClick={() => onChange(cycle === "4w" ? "annual" : "4w")}
      >
        <span className={[
          "absolute w-3.5 h-3.5 rounded-full bg-indigo-400 transition-all",
          cycle === "annual" ? "translate-x-5" : "translate-x-1",
        ].join(" ")} />
      </div>

      <button
        onClick={() => onChange("annual")}
        className={[
          "text-sm font-medium transition-colors flex items-center gap-1.5",
          cycle === "annual" ? "text-zinc-100" : "text-zinc-500",
        ].join(" ")}
      >
        Annually
        <span className="rounded-full bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 text-xs font-semibold px-2 py-0.5">
          Save 20%
        </span>
      </button>
    </div>
  );
}

// ── Tier card ─────────────────────────────────────────────────────────────────

function TierCard({
  tier, meta, cycle, onSubscribe, loading,
}: {
  tier:        Tier;
  meta:        TierMeta;
  cycle:       Cycle;
  onSubscribe: (tier: Tier, cycle: Cycle) => void;
  loading:     Tier | null;
}) {
  const isPopular = tier === "tier3";
  const isPending = loading === tier;
  const displayPrice  = cycle === "annual" ? ANNUAL_WEEKLY[tier]  : meta.display_price;
  const billingLabel  = cycle === "annual" ? ANNUAL_BILLED[tier] : meta.billing_label;

  return (
    <div className={[
      "relative flex flex-col rounded-2xl border p-6 gap-6 transition-all",
      TIER_ACCENT[tier],
      isPopular ? "scale-105 shadow-xl shadow-amber-500/10" : "",
    ].join(" ")}>

      {/* Popular badge */}
      {isPopular && (
        <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 flex items-center gap-1.5 rounded-full bg-amber-500 px-3 py-0.5 text-zinc-900 text-xs font-bold">
          <Star className="w-3 h-3" fill="currentColor" /> Most Popular
        </div>
      )}

      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-zinc-800 border border-zinc-700">
            {TIER_ICONS[tier]}
          </div>
          <span className="text-zinc-100 font-semibold">{meta.name}</span>
        </div>
        <div className="flex gap-1">
          {meta.exchange_access.includes("kraken") && (
            <span className="text-xs rounded-full border border-zinc-700 px-2 py-0.5 text-zinc-500 font-mono">
              Kraken
            </span>
          )}
          {meta.exchange_access.includes("alpaca") && (
            <span className="text-xs rounded-full border border-zinc-700 px-2 py-0.5 text-zinc-500 font-mono">
              Alpaca
            </span>
          )}
        </div>
      </div>

      {/* Price */}
      <div>
        <div className="text-3xl font-black text-zinc-100 tracking-tight">
          {displayPrice}
        </div>
        <div className="text-zinc-500 text-xs mt-1">{billingLabel}</div>
        {cycle === "annual" && (
          <div className="text-emerald-400 text-xs font-semibold mt-1">
            20% savings vs. 4-week billing
          </div>
        )}
      </div>

      {/* Features */}
      <ul className="flex flex-col gap-2.5 flex-1">
        {meta.features.map((feat) => (
          <li key={feat} className="flex items-start gap-2.5">
            <Check className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
            <span className="text-zinc-400 text-sm leading-relaxed">{feat}</span>
          </li>
        ))}
      </ul>

      {/* CTA */}
      <button
        onClick={() => onSubscribe(tier, cycle)}
        disabled={isPending}
        className={[
          "w-full flex items-center justify-center gap-2 rounded-xl py-3 text-sm font-bold transition-colors disabled:opacity-60",
          TIER_BTN[tier],
          tier !== "tier3" ? "text-white" : "",
        ].join(" ")}
      >
        {isPending ? (
          <><Loader2 className="w-4 h-4 animate-spin" /> Redirecting to Stripe…</>
        ) : (
          <>Subscribe</>
        )}
      </button>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Pricing() {
  const [cycle,   setCycle]   = useState<Cycle>("4w");
  const [loading, setLoading] = useState<Tier | null>(null);
  const [error,   setError]   = useState<string | null>(null);

  // Static tier defs (backend mirrors these)
  const TIERS: Record<Tier, TierMeta> = {
    tier1: {
      name:          "Crypto Engine",
      display_price: "$4.99 / week",
      billing_label: "Billed upfront as $19.96 every 4 weeks",
      exchange_access: ["kraken"],
      features: [
        "10-symbol 24/7 Kraken mean-reversion bot",
        "RSI + Z-score dual-signal alerts",
        "1-click trade execution (Kraken)",
        "Live insight dashboard",
        "Up to 10 simultaneous positions",
      ],
    },
    tier2: {
      name:          "Equities Engine",
      display_price: "$9.99 / week",
      billing_label: "Billed upfront as $39.96 every 4 weeks",
      exchange_access: ["alpaca"],
      features: [
        "AI-driven US equity signals (Alpaca)",
        "Groq Llama 3.3 70B market analysis",
        "Profit vault + ratchet stop system",
        "Economic calendar & earnings data",
        "Post-mortem trade analytics",
      ],
    },
    tier3: {
      name:          "Combined Hub",
      display_price: "$12.99 / week",
      billing_label: "Billed upfront as $51.96 every 4 weeks",
      exchange_access: ["kraken", "alpaca"],
      badge:         "Most Popular",
      features: [
        "Everything in Crypto Engine",
        "Everything in Equities Engine",
        "Combined unified dashboard",
        "Cross-asset portfolio analytics",
        "Priority signal delivery",
      ],
    },
  };

  async function handleSubscribe(tier: Tier, c: Cycle) {
    setLoading(tier);
    setError(null);
    try {
      const res  = await fetch(apiUrl("/stripe/checkout"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier, cycle: c }),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        throw new Error(data.error || data.detail || "Checkout failed");
      }
      if (data.url) {
        window.location.href = data.url;
      } else {
        throw new Error("No checkout URL returned");
      }
    } catch (err: any) {
      setError(err.message ?? "Unexpected error");
      setLoading(null);
    }
  }

  return (
    <div className="w-full px-6 py-12 flex flex-col items-center gap-10">

      {/* ── Hero ────────────────────────────────────────────────────────── */}
      <div className="text-center max-w-xl">
        <h1 className="text-3xl md:text-4xl font-black text-zinc-100 tracking-tight">
          Simple, Transparent Pricing
        </h1>
        <p className="mt-3 text-zinc-400 text-sm md:text-base leading-relaxed">
          Choose the engine that matches your market. Cancel or upgrade any time —
          Stripe handles proration automatically.
        </p>
      </div>

      {/* ── Cycle toggle ────────────────────────────────────────────────── */}
      <CycleToggle cycle={cycle} onChange={setCycle} />

      {/* ── Error state ─────────────────────────────────────────────────── */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-2.5 text-red-400 text-sm max-w-md">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* ── Tier grid ───────────────────────────────────────────────────── */}
      <div className="w-full max-w-4xl grid grid-cols-1 md:grid-cols-3 gap-5 items-start">
        {TIER_ORDER.map((tier) => (
          <TierCard
            key={tier}
            tier={tier}
            meta={TIERS[tier]}
            cycle={cycle}
            onSubscribe={handleSubscribe}
            loading={loading}
          />
        ))}
      </div>

      {/* ── Trust signals ───────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 w-full max-w-2xl text-center">
        {[
          { icon: "🔒", label: "Stripe-secured checkout" },
          { icon: "↩️", label: "Cancel anytime" },
          { icon: "⚡", label: "Access activated instantly" },
        ].map(({ icon, label }) => (
          <div key={label} className="flex flex-col items-center gap-1.5">
            <span className="text-xl">{icon}</span>
            <span className="text-zinc-600 text-xs">{label}</span>
          </div>
        ))}
      </div>

      {/* ── FAQ ─────────────────────────────────────────────────────────── */}
      <div className="w-full max-w-xl flex flex-col gap-4">
        <h2 className="text-zinc-400 text-sm font-semibold text-center uppercase tracking-widest">
          Common Questions
        </h2>
        {[
          {
            q: "What happens when I upgrade?",
            a: "Stripe automatically prorates the difference. You only pay for the unused time on the new tier — no manual calculations.",
          },
          {
            q: "Can I try before subscribing?",
            a: "Yes — the dashboard is fully accessible in dev mode with live paper trading data before you subscribe.",
          },
          {
            q: "When does access activate?",
            a: "Immediately after checkout completes. Stripe sends a webhook that provisions your account in seconds.",
          },
        ].map(({ q, a }) => (
          <div key={q} className="rounded-xl border border-zinc-800 bg-zinc-900 px-5 py-4">
            <div className="text-zinc-300 text-sm font-semibold mb-1">{q}</div>
            <div className="text-zinc-500 text-xs leading-relaxed">{a}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
