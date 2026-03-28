/**
 * Settings.tsx — Connect Your Exchange
 * API key management page (stored locally; Stage 5 activates execution).
 */

import { useState, useEffect } from "react";
import { Key, Eye, EyeOff, Save, CheckCircle, Info, SlidersHorizontal } from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface KeyPair {
  apiKey: string;
  apiSecret: string;
  saved: boolean;
}

interface RiskSettings {
  positionSizePct: number;
  maxPositions: number;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ExchangeCard({
  name,
  logo,
  description,
  storageKey,
}: {
  name: string;
  logo: string;
  description: string;
  storageKey: string;
}) {
  const [keys, setKeys] = useState<KeyPair>({ apiKey: "", apiSecret: "", saved: false });
  const [showSecret, setShowSecret] = useState(false);
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(storageKey);
    if (stored) {
      const parsed = JSON.parse(stored);
      setKeys({ ...parsed, saved: true });
    }
  }, [storageKey]);

  function handleSave() {
    const toStore = { apiKey: keys.apiKey, apiSecret: keys.apiSecret };
    localStorage.setItem(storageKey, JSON.stringify(toStore));
    setKeys((k) => ({ ...k, saved: true }));
    setJustSaved(true);
    setTimeout(() => setJustSaved(false), 2000);
  }

  function handleClear() {
    localStorage.removeItem(storageKey);
    setKeys({ apiKey: "", apiSecret: "", saved: false });
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      {/* Card header */}
      <div className="px-6 py-4 border-b border-zinc-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-zinc-800 text-base">
            {logo}
          </span>
          <div>
            <div className="text-zinc-100 text-sm font-semibold">{name}</div>
            <div className="text-zinc-500 text-xs">{description}</div>
          </div>
        </div>
        {keys.saved && (
          <span className="flex items-center gap-1.5 text-emerald-400 text-xs font-medium">
            <CheckCircle className="w-3.5 h-3.5" />
            Keys saved
          </span>
        )}
      </div>

      {/* Inputs */}
      <div className="px-6 py-5 flex flex-col gap-4">
        {/* API Key */}
        <div className="flex flex-col gap-1.5">
          <label className="text-zinc-400 text-xs font-medium flex items-center gap-1.5">
            <Key className="w-3 h-3" /> API Key
          </label>
          <input
            type="text"
            placeholder="Paste your API key…"
            value={keys.apiKey}
            onChange={(e) => setKeys((k) => ({ ...k, apiKey: e.target.value, saved: false }))}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-zinc-200 text-sm font-mono placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        {/* API Secret */}
        <div className="flex flex-col gap-1.5">
          <label className="text-zinc-400 text-xs font-medium flex items-center gap-1.5">
            <Key className="w-3 h-3" /> API Secret
          </label>
          <div className="relative">
            <input
              type={showSecret ? "text" : "password"}
              placeholder="Paste your API secret…"
              value={keys.apiSecret}
              onChange={(e) => setKeys((k) => ({ ...k, apiSecret: e.target.value, saved: false }))}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 pr-10 text-zinc-200 text-sm font-mono placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <button
              type="button"
              onClick={() => setShowSecret((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-600 hover:text-zinc-400"
            >
              {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={handleSave}
            disabled={!keys.apiKey || !keys.apiSecret}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed px-4 py-2 text-white text-sm font-medium transition-colors"
          >
            {justSaved ? (
              <CheckCircle className="w-4 h-4" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {justSaved ? "Saved!" : "Save Keys"}
          </button>
          {keys.saved && (
            <button
              onClick={handleClear}
              className="text-zinc-600 hover:text-red-400 text-xs transition-colors"
            >
              Clear
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Risk settings card ────────────────────────────────────────────────────────

function RiskCard() {
  const [settings, setSettings] = useState<RiskSettings>({
    positionSizePct: 10,
    maxPositions: 10,
  });

  useEffect(() => {
    const stored = localStorage.getItem("algoedge_risk");
    if (stored) setSettings(JSON.parse(stored));
  }, []);

  function handleSave() {
    localStorage.setItem("algoedge_risk", JSON.stringify(settings));
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="px-6 py-4 border-b border-zinc-800 flex items-center gap-3">
        <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-zinc-800">
          <SlidersHorizontal className="w-4 h-4 text-zinc-400" />
        </span>
        <div>
          <div className="text-zinc-100 text-sm font-semibold">Risk Settings</div>
          <div className="text-zinc-500 text-xs">Position sizing and exposure limits</div>
        </div>
      </div>

      <div className="px-6 py-5 flex flex-col gap-5">
        {/* Position size */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label className="text-zinc-400 text-xs font-medium">
              Max position size (% of equity)
            </label>
            <span className="text-indigo-400 text-sm font-mono font-bold">
              {settings.positionSizePct}%
            </span>
          </div>
          <input
            type="range"
            min={1}
            max={25}
            step={1}
            value={settings.positionSizePct}
            onChange={(e) =>
              setSettings((s) => ({ ...s, positionSizePct: Number(e.target.value) }))
            }
            className="w-full accent-indigo-500"
          />
          <div className="flex justify-between text-zinc-700 text-xs">
            <span>1%</span>
            <span>25%</span>
          </div>
        </div>

        {/* Max positions */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label className="text-zinc-400 text-xs font-medium">
              Maximum simultaneous positions
            </label>
            <span className="text-indigo-400 text-sm font-mono font-bold">
              {settings.maxPositions}
            </span>
          </div>
          <input
            type="range"
            min={1}
            max={10}
            step={1}
            value={settings.maxPositions}
            onChange={(e) =>
              setSettings((s) => ({ ...s, maxPositions: Number(e.target.value) }))
            }
            className="w-full accent-indigo-500"
          />
          <div className="flex justify-between text-zinc-700 text-xs">
            <span>1</span>
            <span>10</span>
          </div>
        </div>

        <button
          onClick={handleSave}
          className="flex items-center gap-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 px-4 py-2 text-zinc-300 text-sm font-medium transition-colors w-fit"
        >
          <Save className="w-4 h-4" />
          Save Risk Settings
        </button>
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Settings() {
  return (
    <div className="w-full max-w-2xl mx-auto px-6 py-10 flex flex-col gap-8">
      {/* Header */}
      <div>
        <h1 className="text-zinc-100 text-xl font-bold">Connect Your Exchange</h1>
        <p className="mt-1 text-zinc-500 text-sm">
          API keys are stored in your browser only — never sent to any server in the current build.
        </p>
      </div>

      {/* Stage 5 notice */}
      <div className="flex items-start gap-3 rounded-xl border border-indigo-500/20 bg-indigo-500/5 px-4 py-3">
        <Info className="w-4 h-4 text-indigo-400 mt-0.5 shrink-0" />
        <p className="text-indigo-300 text-xs leading-relaxed">
          <span className="font-semibold">Stage 5</span> activates 1-click execution using these keys.
          Until then, saving them here stores them in{" "}
          <span className="font-mono">localStorage</span> and prepares the connection for when
          execution middleware is enabled.
        </p>
      </div>

      {/* Exchange cards */}
      <ExchangeCard
        name="Kraken"
        logo="🐙"
        description="Spot + margin trading · Mean-reversion bot"
        storageKey="algoedge_kraken"
      />
      <ExchangeCard
        name="Alpaca"
        logo="🦙"
        description="US equities + crypto · Paper trading"
        storageKey="algoedge_alpaca"
      />

      {/* Risk settings */}
      <RiskCard />
    </div>
  );
}
