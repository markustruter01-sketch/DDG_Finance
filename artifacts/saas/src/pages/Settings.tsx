/**
 * Settings.tsx — Connect Your Exchange + Live Mode Toggle
 * Stage 5: Live Mode switch wires saved API keys into the 1-click execution path.
 */

import { useState, useEffect } from "react";
import {
  Key, Eye, EyeOff, Save, CheckCircle, Info,
  SlidersHorizontal, Radio, ShieldCheck, AlertTriangle,
} from "lucide-react";

// ── Live Mode Toggle ──────────────────────────────────────────────────────────

function LiveModeCard() {
  const [live, setLive] = useState(false);

  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem("algoedge_live_mode") ?? "false");
      setLive(stored);
    } catch { /* ignore */ }
  }, []);

  function toggle() {
    const next = !live;
    setLive(next);
    localStorage.setItem("algoedge_live_mode", JSON.stringify(next));
  }

  return (
    <div className={[
      "rounded-2xl border overflow-hidden transition-colors",
      live ? "border-red-500/40 bg-red-500/5" : "border-zinc-800 bg-zinc-900",
    ].join(" ")}>
      <div className="px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className={[
            "inline-flex items-center justify-center w-8 h-8 rounded-lg",
            live ? "bg-red-500/20" : "bg-zinc-800",
          ].join(" ")}>
            {live
              ? <Radio className="w-4 h-4 text-red-400 animate-pulse" />
              : <ShieldCheck className="w-4 h-4 text-zinc-400" />
            }
          </span>
          <div>
            <div className={["text-sm font-semibold", live ? "text-red-300" : "text-zinc-100"].join(" ")}>
              {live ? "LIVE MODE ACTIVE" : "Live Trading Mode"}
            </div>
            <div className="text-zinc-500 text-xs">
              {live
                ? "Trades execute on your real Kraken account with real funds"
                : "Currently in safe paper mode — no real money used"
              }
            </div>
          </div>
        </div>

        {/* Toggle switch */}
        <button
          onClick={toggle}
          className={[
            "relative inline-flex items-center h-6 w-11 rounded-full transition-colors focus:outline-none",
            live ? "bg-red-500" : "bg-zinc-700",
          ].join(" ")}
        >
          <span className={[
            "inline-block w-4 h-4 rounded-full bg-white shadow transition-transform",
            live ? "translate-x-6" : "translate-x-1",
          ].join(" ")} />
        </button>
      </div>

      {live && (
        <div className="px-6 pb-4">
          <div className="flex items-start gap-2 rounded-lg border border-red-500/20 bg-red-500/8 px-3 py-2.5">
            <AlertTriangle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
            <div className="flex flex-col gap-1">
              <span className="text-red-300 text-xs font-semibold">Real money at risk</span>
              <p className="text-red-400/80 text-xs leading-relaxed">
                Every trade executed from the Dashboard will submit a real market order
                to Kraken using your saved API keys. Ensure your keys have trading
                permissions and that you understand the risk.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Exchange Card ─────────────────────────────────────────────────────────────

function ExchangeCard({
  name, logo, description, storageKey,
}: {
  name: string; logo: string; description: string; storageKey: string;
}) {
  const [keys, setKeys]       = useState({ apiKey: "", apiSecret: "", saved: false });
  const [showSecret, setShow] = useState(false);
  const [justSaved, setJust]  = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(storageKey);
    if (stored) setKeys({ ...JSON.parse(stored), saved: true });
  }, [storageKey]);

  function handleSave() {
    localStorage.setItem(storageKey, JSON.stringify({ apiKey: keys.apiKey, apiSecret: keys.apiSecret }));
    setKeys((k) => ({ ...k, saved: true }));
    setJust(true);
    setTimeout(() => setJust(false), 2000);
  }

  function handleClear() {
    localStorage.removeItem(storageKey);
    setKeys({ apiKey: "", apiSecret: "", saved: false });
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="px-6 py-4 border-b border-zinc-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-zinc-800 text-base">{logo}</span>
          <div>
            <div className="text-zinc-100 text-sm font-semibold">{name}</div>
            <div className="text-zinc-500 text-xs">{description}</div>
          </div>
        </div>
        {keys.saved && (
          <span className="flex items-center gap-1.5 text-emerald-400 text-xs font-medium">
            <CheckCircle className="w-3.5 h-3.5" /> Keys saved
          </span>
        )}
      </div>

      <div className="px-6 py-5 flex flex-col gap-4">
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
              onClick={() => setShow((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-600 hover:text-zinc-400"
            >
              {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={handleSave}
            disabled={!keys.apiKey || !keys.apiSecret}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed px-4 py-2 text-white text-sm font-medium transition-colors"
          >
            {justSaved ? <CheckCircle className="w-4 h-4" /> : <Save className="w-4 h-4" />}
            {justSaved ? "Saved!" : "Save Keys"}
          </button>
          {keys.saved && (
            <button onClick={handleClear} className="text-zinc-600 hover:text-red-400 text-xs transition-colors">
              Clear
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Risk Card ─────────────────────────────────────────────────────────────────

function RiskCard() {
  const [settings, setSettings] = useState({ positionSizePct: 10, maxPositions: 10 });

  useEffect(() => {
    const stored = localStorage.getItem("algoedge_risk");
    if (stored) setSettings(JSON.parse(stored));
  }, []);

  function save() {
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
          <div className="text-zinc-500 text-xs">Controls default size in the Trade Modal</div>
        </div>
      </div>

      <div className="px-6 py-5 flex flex-col gap-5">
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label className="text-zinc-400 text-xs font-medium">Default position size (% of balance)</label>
            <span className="text-indigo-400 text-sm font-mono font-bold">{settings.positionSizePct}%</span>
          </div>
          <input type="range" min={1} max={25} step={1} value={settings.positionSizePct}
            onChange={(e) => setSettings((s) => ({ ...s, positionSizePct: Number(e.target.value) }))}
            className="w-full accent-indigo-500" />
          <div className="flex justify-between text-zinc-700 text-xs"><span>1%</span><span>25%</span></div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label className="text-zinc-400 text-xs font-medium">Maximum simultaneous positions</label>
            <span className="text-indigo-400 text-sm font-mono font-bold">{settings.maxPositions}</span>
          </div>
          <input type="range" min={1} max={10} step={1} value={settings.maxPositions}
            onChange={(e) => setSettings((s) => ({ ...s, maxPositions: Number(e.target.value) }))}
            className="w-full accent-indigo-500" />
          <div className="flex justify-between text-zinc-700 text-xs"><span>1</span><span>10</span></div>
        </div>

        <button onClick={save}
          className="flex items-center gap-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 px-4 py-2 text-zinc-300 text-sm font-medium transition-colors w-fit">
          <Save className="w-4 h-4" /> Save Risk Settings
        </button>
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Settings() {
  return (
    <div className="w-full max-w-2xl mx-auto px-6 py-10 flex flex-col gap-6">
      <div>
        <h1 className="text-zinc-100 text-xl font-bold">Connect Your Exchange</h1>
        <p className="mt-1 text-zinc-500 text-sm">
          API keys stay in your browser. Enable Live Mode to wire them into 1-click execution.
        </p>
      </div>

      {/* Live Mode — most prominent, at the top */}
      <LiveModeCard />

      {/* Stage 5 info */}
      <div className="flex items-start gap-3 rounded-xl border border-indigo-500/20 bg-indigo-500/5 px-4 py-3">
        <Info className="w-4 h-4 text-indigo-400 mt-0.5 shrink-0" />
        <p className="text-indigo-300 text-xs leading-relaxed">
          <span className="font-semibold">Stage 5 is active.</span> Save your Kraken API key
          below, then enable Live Mode above. From that point, every trade you execute on the
          Dashboard will submit a real order. Paper Mode uses a separate $10K demo portfolio
          with no risk.
        </p>
      </div>

      <ExchangeCard name="Kraken" logo="🐙" description="Spot + margin · Mean-reversion bot" storageKey="algoedge_kraken" />
      <ExchangeCard name="Alpaca" logo="🦙" description="US equities + crypto · Paper trading" storageKey="algoedge_alpaca" />
      <RiskCard />
    </div>
  );
}
