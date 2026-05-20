import { useRef, useMemo, useEffect, useState } from "react";
import { DDGBadge } from "@/components/DDGBadge";
import { useRealFeed } from "@/components/streaming/useRealFeed";
import {
  useLivePositions,
  useLearningJournal,
  useKrakenStatus,
  useOptionsState,
  useForexState,
  useAuditorReport,
  useAdminLearningSnapshot,
  usePoseidonState,
  useKrakenCurrentState,
  useFleetEquity,
  useBotRegistry,
} from "@/hooks/use-trading";
import { getFleetBotCount } from "@/lib/fleet-capital";
import { onTradePulse } from "@/components/streaming/tradePulseEvents";
import { TradingEngineBlackHole } from "@/components/streaming/TradingEngineBlackHole";

// ─── Algorithmic Thought Bubbles ─────────────────────────────────────────────

const ALGO_THOUGHTS = [
  "MACD: signal > baseline → BUY",
  "RSI(14) = 68.4 → overbought",
  "Kelly f* = 0.23",
  "Sharpe = 1.87",
  "EMA(9) > EMA(21) ✓",
  "σ(vol) = 0.024",
  "regime: BULL ↑",
  "BTC/USD: 4h engulfing",
  "vol crush → IV = 22%",
  "momentum: +2.4σ",
  "max drawdown: 4.2%",
  "win_rate = 54.3%",
  "profit_factor = 1.87",
  "Δ = 0.67, Γ = 0.12",
  "ADX = 28.3 → trending",
  "Bollinger squeeze → breakout",
  "θ = -0.043 / day",
  "liquidity = OK",
  "regime: Crypto-Risk-Off × 0.5",
  "pair corr(BTC,ETH) = 0.91",
  "news sentiment: neutral",
  "stoch K < 20 → oversold",
  "ATR(14) = 142.6",
  "VWAP deviation: +0.8%",
  "WFO optimised ✓",
  "position sizing: 2.0%",
  "signal confidence: 74%",
];

type AlgoThought = {
  id: number;
  text: string;
  x: number;
  y: number;
  opacity: number;
  fadeIn: boolean;
  color: string;
};

function AlgoThoughts() {
  const [thoughts, setThoughts] = useState<AlgoThought[]>([]);
  const nextId = useRef(0);
  const colors = ["#22d3ee", "#a78bfa", "#4ade80", "#fb923c", "#f472b6", "#facc15", "#6366f1", "#06b6d4"];

  useEffect(() => {
    const spawn = () => {
      const id = nextId.current++;
      const text = ALGO_THOUGHTS[Math.floor(Math.random() * ALGO_THOUGHTS.length)];
      const side  = Math.random();
      let x: number, y: number;
      if (side < 0.25)       { x = 4 + Math.random() * 18; y = 8 + Math.random() * 80; }
      else if (side < 0.5)   { x = 78 + Math.random() * 18; y = 8 + Math.random() * 80; }
      else if (side < 0.75)  { x = 20 + Math.random() * 60; y = 4 + Math.random() * 12; }
      else                   { x = 20 + Math.random() * 60; y = 82 + Math.random() * 12; }

      const color = colors[Math.floor(Math.random() * colors.length)];
      const thought: AlgoThought = { id, text, x, y, opacity: 0, fadeIn: true, color };
      setThoughts(prev => [...prev.slice(-8), thought]);

      setTimeout(() => setThoughts(prev => prev.map(t => t.id === id ? { ...t, opacity: 1, fadeIn: false } : t)), 50);
      setTimeout(() => setThoughts(prev => prev.map(t => t.id === id ? { ...t, opacity: 0 } : t)), 3200);
      setTimeout(() => setThoughts(prev => prev.filter(t => t.id !== id)), 4000);

      const delay = 3500 + Math.random() * 3000;
      setTimeout(spawn, delay);
    };

    const initial = setTimeout(spawn, 1200 + Math.random() * 1000);
    return () => clearTimeout(initial);
  }, []);

  return (
    <>
      {thoughts.map(t => (
        <div
          key={t.id}
          style={{
            position: "absolute",
            left: `${t.x}%`,
            top:  `${t.y}%`,
            transform: "translate(-50%, -50%)",
            opacity: t.opacity,
            transition: "opacity 0.7s ease",
            pointerEvents: "none",
            userSelect: "none",
            fontFamily: "monospace",
            fontSize: 11,
            fontWeight: 700,
            color: t.color,
            textShadow: `0 0 10px ${t.color}88, 0 0 20px ${t.color}44`,
            background: "rgba(2,6,23,0.7)",
            border: `1px solid ${t.color}44`,
            borderRadius: 6,
            padding: "3px 8px",
            letterSpacing: "0.05em",
            whiteSpace: "nowrap",
          }}
        >
          {t.text}
        </div>
      ))}
    </>
  );
}

// ─── Main OrbVisualiser ───────────────────────────────────────────────────────

interface TradePulseState {
  active:  boolean;
  isWin:   boolean;
  botName: string;
  ts:      number;
}

export function OrbVisualiser() {
  const { data: livePos       } = useLivePositions();
  const { data: journal       } = useLearningJournal(undefined, undefined, 5);
  const { data: djStatus      } = useKrakenStatus("davy-jones");
  const { data: bbStatus      } = useKrakenStatus("blackbeard");
  const { data: optState      } = useOptionsState();
  const { data: fxState       } = useForexState();
  const { data: poseidonState } = usePoseidonState();
  const { data: kcState       } = useKrakenCurrentState();
  const { data: auditor       } = useAuditorReport();
  const { data: snapshot      } = useAdminLearningSnapshot();
  const { data: fleetEqOrb    } = useFleetEquity();
  const { data: registry      } = useBotRegistry();
  const { trades: closedTradesFeed, openPositions: openTradesFeed } = useRealFeed(12);

  const [tradePulse, setTradePulse] = useState<TradePulseState | null>(null);
  const [aiRipple,   setAiRipple  ] = useState(false);
  const lastJournalCount = useRef<number | null>(null);
  const lastAuditorRunAt = useRef<string | null>(null);

  // Trade pulse events
  useEffect(() => {
    const unsub = onTradePulse((ev) => {
      setTradePulse({ active: true, isWin: ev.type === "win", botName: ev.botName, ts: Date.now() });
      setTimeout(() => setTradePulse(null), 2500);
    });
    return unsub;
  }, []);

  // AI ripple on learning-journal count change
  useEffect(() => {
    const count = journal?.count ?? null;
    if (lastJournalCount.current !== null && count !== null && count !== lastJournalCount.current) {
      setAiRipple(true); setTimeout(() => setAiRipple(false), 3000);
    }
    if (count !== null) lastJournalCount.current = count;
  }, [journal?.count]);

  // AI ripple on auditor run
  useEffect(() => {
    const runAt = auditor?.report?.run_at ?? null;
    if (lastAuditorRunAt.current !== null && runAt !== null && runAt !== lastAuditorRunAt.current) {
      setAiRipple(true); setTimeout(() => setAiRipple(false), 3000);
    }
    if (runAt !== null) lastAuditorRunAt.current = runAt;
  }, [auditor?.report?.run_at]);

  // ── Derived data ─────────────────────────────────────────────────────────

  const openPositions = useMemo(() => {
    let n = livePos?.count ?? 0;
    n += djStatus?.position_count ?? 0;
    n += bbStatus?.position_count ?? 0;
    n += optState?.positions_count ?? 0;
    n += fxState?.position_count ?? 0;
    n += poseidonState?.open_positions ?? 0;
    n += kcState?.open_positions ?? 0;
    return n;
  }, [livePos, djStatus, bbStatus, fleetEqOrb, optState, fxState, poseidonState, kcState]);

  const activeBots = useMemo(() => {
    const ACTIVE_STATUSES = new Set(["active", "running", "idle"]);
    return (registry?.bots ?? []).filter(b => ACTIVE_STATUSES.has((b.status ?? "").toLowerCase())).length;
  }, [registry]);

  const lastAiTs = useMemo(() => {
    const journalTs  = journal?.entries?.[0]?.last_seen ? new Date(journal.entries[0].last_seen).getTime() : 0;
    const auditorTs  = auditor?.report?.run_at          ? new Date(auditor.report.run_at).getTime()        : 0;
    const snapshotTs = snapshot?.exported_at            ? new Date(snapshot.exported_at).getTime()         : 0;
    return Math.max(journalTs, auditorTs, snapshotTs);
  }, [journal, auditor, snapshot]);

  const combinedPnl = fleetEqOrb?.fleet_total?.pnl ?? 0;

  function fmtPnl(v: number) {
    const abs = Math.abs(v);
    const s   = v >= 0 ? "+" : "-";
    if (abs >= 1_000_000) return `${s}$${(abs / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000)     return `${s}$${(abs / 1_000).toFixed(1)}k`;
    return `${s}$${abs.toFixed(0)}`;
  }

  const lastAiLabel = useMemo(() => {
    if (!lastAiTs) return "never";
    const diff = Date.now() - lastAiTs;
    const mins = Math.floor(diff / 60_000);
    if (mins < 1)  return "just now";
    if (mins < 60) return `${mins}m ago`;
    return `${Math.floor(mins / 60)}h ago`;
  }, [lastAiTs]);

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <div style={{ width: "100%", height: "100%", position: "relative", background: "#020617", overflow: "hidden" }}>
      <TradingEngineBlackHole />

      {/* ── LIVE ORB HUD — 30% larger ── */}
      <div
        style={{
          position: "absolute",
          bottom: 24,
          right: 24,
          background: "rgba(2,6,23,0.82)",
          border: "1px solid rgba(251,146,60,0.3)",
          borderRadius: 14,
          padding: "18px 24px",
          backdropFilter: "blur(14px)",
          minWidth: 234,
        }}
      >
        <div style={{ color: "rgba(148,163,184,0.55)", fontSize: 11, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", marginBottom: 12 }}>
          Live Orb HUD
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 20px" }}>
          <div>
            <div style={{ color: "rgba(148,163,184,0.5)", fontSize: 10, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 }}>P&amp;L</div>
            <div style={{ color: combinedPnl >= 0 ? "#4ade80" : "#f87171", fontSize: 18, fontFamily: "monospace", fontWeight: 700 }}>
              {fmtPnl(combinedPnl)}
            </div>
          </div>

          <div>
            <div style={{ color: "rgba(148,163,184,0.5)", fontSize: 10, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 }}>Positions</div>
            <div style={{ color: "#fbbf24", fontSize: 18, fontFamily: "monospace", fontWeight: 700 }}>
              {openPositions}
            </div>
          </div>

          <div>
            <div style={{ color: "rgba(148,163,184,0.5)", fontSize: 10, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 }}>Active Bots</div>
            <div style={{ color: "#22d3ee", fontSize: 18, fontFamily: "monospace", fontWeight: 700 }}>
              {activeBots} / {getFleetBotCount(registry, fleetEqOrb)}
            </div>
          </div>

          <div>
            <div style={{ color: "rgba(148,163,184,0.5)", fontSize: 10, fontFamily: "monospace", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 2 }}>Last AI Event</div>
            <div style={{ color: "#a78bfa", fontSize: 15, fontFamily: "monospace", fontWeight: 700 }}>
              {lastAiLabel}
            </div>
          </div>
        </div>

        {tradePulse?.active && (
          <div style={{
            marginTop: 12,
            padding: "5px 10px",
            borderRadius: 7,
            background: tradePulse.isWin ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
            border: `1px solid ${tradePulse.isWin ? "rgba(34,197,94,0.4)" : "rgba(239,68,68,0.4)"}`,
            color: tradePulse.isWin ? "#4ade80" : "#f87171",
            fontSize: 11, fontFamily: "monospace", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em",
          }}>
            {tradePulse.isWin ? "✓ WIN" : "✗ LOSS"} — {tradePulse.botName}
          </div>
        )}

        {aiRipple && (
          <div style={{
            marginTop: 8,
            padding: "5px 10px",
            borderRadius: 7,
            background: "rgba(139,92,246,0.15)",
            border: "1px solid rgba(139,92,246,0.4)",
            color: "#a78bfa",
            fontSize: 11, fontFamily: "monospace", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em",
          }}>
            ◉ AI Learning Event
          </div>
        )}
      </div>

      {/* ── ALGO THOUGHT BUBBLES ── */}
      <AlgoThoughts />

      {/* ── PROMINENT TITLE ── */}
      <div
        style={{
          position: "absolute",
          top: 20,
          left: "50%",
          transform: "translateX(-50%)",
          textAlign: "center",
          pointerEvents: "none",
          userSelect: "none",
        }}
      >
        <div style={{
          color: "rgba(251,146,60,0.95)",
          fontSize: 18,
          fontFamily: "monospace",
          fontWeight: 700,
          letterSpacing: "0.35em",
          textTransform: "uppercase",
          textShadow: "0 0 20px rgba(251,146,60,0.8), 0 0 40px rgba(251,146,60,0.4), 0 0 60px rgba(234,88,12,0.3)",
        }}>
          ◈ TRADING ENGINE ◈
        </div>
        <div style={{
          color: "rgba(251,146,60,0.5)",
          fontSize: 10,
          fontFamily: "monospace",
          letterSpacing: "0.25em",
          textTransform: "uppercase",
          marginTop: 4,
          textShadow: "0 0 12px rgba(251,146,60,0.4)",
        }}>
          LIVE MARKET CONSCIOUSNESS
        </div>
      </div>

      {/* ── LEFT PANEL: RECENTLY CLOSED TRADES ── */}
      {closedTradesFeed.length > 0 && (
        <div
          style={{
            position: "absolute",
            left: 16,
            top: 10,
            bottom: 52,
            width: 216,
            display: "flex",
            flexDirection: "column",
            overflowY: "auto",
            zIndex: 20,
          }}
        >
          <div style={{ color: "rgba(255,255,255,0.9)", fontSize: 9, fontFamily: "monospace", letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 6, paddingLeft: 2, fontWeight: 600 }}>
            ◂ Closed Trades
          </div>
          {closedTradesFeed.slice(0, 10).map((t, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "5px 8px",
                marginBottom: 3,
                borderRadius: 7,
                background: t.isWin ? "rgba(34,197,94,0.07)" : "rgba(239,68,68,0.07)",
                border: `1px solid ${t.isWin ? "rgba(34,197,94,0.18)" : "rgba(239,68,68,0.18)"}`,
                backdropFilter: "blur(10px)",
              }}
            >
              <span style={{ fontSize: 10, color: t.isWin ? "#4ade80" : "#f87171", flexShrink: 0, fontFamily: "monospace" }}>
                {t.isWin ? "✓" : "✗"}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: "monospace", fontSize: 10, color: "rgba(241,245,249,0.85)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {t.symbol}
                </div>
                <div style={{ fontFamily: "monospace", fontSize: 8, color: "rgba(148,163,184,0.5)", letterSpacing: "0.05em" }}>
                  {t.bot}
                </div>
              </div>
              <span style={{ fontFamily: "monospace", fontSize: 10, fontWeight: 700, color: t.isWin ? "#4ade80" : "#f87171", flexShrink: 0 }}>
                {t.pnlUsd >= 0 ? "+" : ""}${Math.abs(t.pnlUsd) >= 1000 ? `${(Math.abs(t.pnlUsd) / 1000).toFixed(1)}k` : Math.abs(t.pnlUsd).toFixed(0)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── RIGHT PANEL: OPEN POSITIONS ── */}
      {openTradesFeed.length > 0 && (
        <div
          style={{
            position: "absolute",
            right: 16,
            top: 10,
            bottom: 240,
            width: 216,
            display: "flex",
            flexDirection: "column",
            overflowY: "auto",
            zIndex: 20,
          }}
        >
          <div style={{ color: "rgba(255,255,255,0.9)", fontSize: 9, fontFamily: "monospace", letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 6, textAlign: "right", paddingRight: 2, fontWeight: 600 }}>
            Open Positions ▸
          </div>
          {openTradesFeed.slice(0, 10).map((p, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "5px 8px",
                marginBottom: 3,
                borderRadius: 7,
                background: (p.pnlUsd ?? 0) >= 0 ? "rgba(52,211,153,0.07)" : "rgba(239,68,68,0.07)",
                border: `1px solid ${(p.pnlUsd ?? 0) >= 0 ? "rgba(52,211,153,0.18)" : "rgba(239,68,68,0.18)"}`,
                backdropFilter: "blur(10px)",
              }}
            >
              <span style={{ fontSize: 8, color: (p.pnlUsd ?? 0) >= 0 ? "#34d399" : "#f87171", flexShrink: 0 }}>⬤</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: "monospace", fontSize: 10, color: "rgba(241,245,249,0.85)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {p.symbol}
                </div>
                <div style={{ fontFamily: "monospace", fontSize: 8, color: "rgba(148,163,184,0.5)", letterSpacing: "0.05em" }}>
                  {p.bot}
                </div>
              </div>
              <span style={{ fontFamily: "monospace", fontSize: 10, fontWeight: 700, color: (p.pnlUsd ?? 0) >= 0 ? "#34d399" : "#f87171", flexShrink: 0 }}>
                {(p.pnlUsd ?? 0) >= 0 ? "+" : ""}${Math.abs(p.pnlUsd ?? 0) >= 1000 ? `${(Math.abs(p.pnlUsd ?? 0) / 1000).toFixed(1)}k` : Math.abs(p.pnlUsd ?? 0).toFixed(0)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── DDG BADGE ── */}
      <DDGBadge style={{ position: "absolute", bottom: 16, left: 16, zIndex: 30 }} />
    </div>
  );
}
