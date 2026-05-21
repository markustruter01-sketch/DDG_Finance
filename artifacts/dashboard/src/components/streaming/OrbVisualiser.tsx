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
  useFleetEquity,
  useBotRegistry,
} from "@/hooks/use-trading";
import { getFleetBotCount } from "@/lib/fleet-capital";
import { onTradePulse } from "@/components/streaming/tradePulseEvents";
import { TradingEngineBlackHole } from "@/components/streaming/TradingEngineBlackHole";
import { MiniSynapticWidget } from "@/components/streaming/MiniSynapticWidget";

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
      // Constrain to the central black-hole zone only —
      // avoids the left widget column (~0–29%), right HUD (~76–100%),
      // top header (~0–18%) and bottom badge/nav (~78–100%).
      const x = 30 + Math.random() * 44;   // 30 % → 74 %
      const y = 18 + Math.random() * 58;   // 18 % → 76 %

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
    return n;
  }, [livePos, djStatus, bbStatus, fleetEqOrb, optState, fxState]);

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
          top: 14,
          left: "50%",
          transform: "translateX(-50%)",
          textAlign: "center",
          pointerEvents: "none",
          userSelect: "none",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 4,
        }}
      >
        {/* DDG logo above title */}
        <DDGBadge style={{ position: "relative", pointerEvents: "none" }} />
        <div style={{
          color: "rgba(251,146,60,0.95)",
          fontSize: 27,
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
          textShadow: "0 0 12px rgba(251,146,60,0.4)",
        }}>
          LIVE MARKET CONSCIOUSNESS
        </div>
      </div>

      {/* ── CLOSED TRADES (346px — same width as Math Audit widget) ── */}
      {closedTradesFeed.length > 0 && (() => {
        const BOT_COLORS: Record<string, string> = {
          "Oracle":        "#8b5cf6",
          "SPY/QQQ Trend": "#22d3ee",
          "Jerome":        "#f97316",
          "Forex Gump":    "#10b981",
        };
        const fmtSize = (v: number) =>
          Math.abs(v) >= 1_000_000 ? `$${(Math.abs(v)/1_000_000).toFixed(1)}M`
          : Math.abs(v) >= 1_000   ? `$${(Math.abs(v)/1_000).toFixed(1)}k`
          : `$${Math.abs(v).toFixed(0)}`;
        // Full integer dollar amount for position size (no abbreviation, no cents)
        const fmtFull = (v: number) =>
          `$${Math.round(Math.abs(v)).toLocaleString()}`;

        return (
          <div
            style={{
              position: "absolute",
              left: 12,
              top: 10,
              bottom: 336,
              width: 346,
              zIndex: 20,
              display: "flex",
              flexDirection: "column",
              overflowY: "auto",
            }}
          >
            <div style={{ color: "rgba(255,255,255,0.9)", fontSize: 18, fontFamily: "monospace", letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 6, paddingLeft: 2, fontWeight: 600 }}>
              ◂ Closed Trades
            </div>
            {closedTradesFeed.slice(0, 10).map((t, i) => {
              const botColor = BOT_COLORS[t.bot] ?? "#94a3b8";
              const side = (t.side || "").toLowerCase();
              const isLong = side === "long" || side === "buy";
              const isShort = side === "short" || side === "sell";
              const sideLabel = isLong ? "L" : isShort ? "S" : null;
              const sideBg    = isLong ? "rgba(34,197,94,0.18)"  : isShort ? "rgba(239,68,68,0.18)" : "transparent";
              const sideColor = isLong ? "#4ade80"               : isShort ? "#f87171"               : "rgba(148,163,184,0.5)";
              // Use explicit sizeUsd from feed; fall back to pnlPct-derived notional when available
              const notional = t.sizeUsd != null
                ? t.sizeUsd
                : (t.pnlPct != null && Math.abs(t.pnlPct) > 0.01
                    ? Math.abs(t.pnlUsd / (t.pnlPct / 100))
                    : null);
              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    padding: "4px 8px",
                    marginBottom: 2,
                    borderRadius: 6,
                    background: t.isWin ? "rgba(34,197,94,0.07)" : "rgba(239,68,68,0.07)",
                    border: `1px solid ${t.isWin ? "rgba(34,197,94,0.18)" : "rgba(239,68,68,0.18)"}`,
                    backdropFilter: "blur(10px)",
                  }}
                >
                  {/* col 1 — bot dot */}
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: botColor, flexShrink: 0, boxShadow: `0 0 5px ${botColor}`, marginRight: 6 }} />
                  {/* col 2 — bot icon */}
                  <span style={{ width: 18, fontSize: 13, flexShrink: 0, lineHeight: 1, marginRight: 6 }}>{t.icon}</span>
                  {/* col 3 — symbol (fixed 72px) */}
                  <span style={{ width: 72, fontFamily: "monospace", fontSize: 12, color: "rgba(241,245,249,0.95)", fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 0, marginRight: 4 }}>
                    {t.symbol}
                  </span>
                  {/* col 4 — side badge (fixed 20px, always present) */}
                  <span style={{ width: 20, flexShrink: 0, marginRight: 6 }}>
                    {sideLabel && (
                      <span style={{ fontSize: 8, fontFamily: "monospace", fontWeight: 800, color: sideColor, background: sideBg, borderRadius: 3, padding: "1px 4px" }}>
                        {sideLabel}
                      </span>
                    )}
                  </span>
                  {/* col 5 — position size (flex, fills gap) */}
                  <span style={{ flex: 1, fontFamily: "monospace", fontSize: 12, fontWeight: 700, color: "rgba(255,255,255,0.9)", whiteSpace: "nowrap", overflow: "hidden" }}>
                    {notional != null ? fmtFull(notional) : ""}
                  </span>
                  {/* col 6 — P&L (fixed 52px, right-aligned) */}
                  <span style={{ width: 52, fontFamily: "monospace", fontSize: 12, fontWeight: 700, color: t.isWin ? "#4ade80" : "#f87171", flexShrink: 0, textAlign: "right", marginRight: 4 }}>
                    {t.pnlUsd >= 0 ? "+" : ""}{fmtSize(t.pnlUsd)}
                  </span>
                  {/* col 7 — win/loss tick (fixed 12px) */}
                  <span style={{ width: 12, fontSize: 11, color: t.isWin ? "#4ade80" : "#f87171", flexShrink: 0, fontFamily: "monospace", textAlign: "center" }}>
                    {t.isWin ? "✓" : "✗"}
                  </span>
                </div>
              );
            })}
          </div>
        );
      })()}

      {/* ── MATH AUDIT WIDGET (346px wide, anchored to bottom) ── */}
      <div
        style={{
          position: "absolute",
          left: 12,
          bottom: 16,
          width: 346,
          height: 280,
          zIndex: 20,
          overflow: "hidden",
        }}
      >
        <MiniSynapticWidget />
      </div>

      {/* ── RIGHT PANEL: OPEN POSITIONS ── */}
      {openTradesFeed.length > 0 && (() => {
        const OP_BOT_COLORS: Record<string, string> = {
          "Oracle":        "#8b5cf6",
          "SPY/QQQ Trend": "#22d3ee",
          "Jerome":        "#f97316",
          "Forex Gump":    "#10b981",
        };
        const fmtOpSize = (v: number) =>
          Math.abs(v) >= 1_000_000 ? `$${(Math.abs(v)/1_000_000).toFixed(1)}M`
          : Math.abs(v) >= 1_000   ? `$${(Math.abs(v)/1_000).toFixed(1)}k`
          : `$${Math.abs(v).toFixed(0)}`;
        const fmtOpFull = (v: number) => `$${Math.round(Math.abs(v)).toLocaleString()}`;

        return (
          <div
            style={{
              position: "absolute",
              right: 16,
              top: 10,
              bottom: 312,
              width: 280,
              display: "flex",
              flexDirection: "column",
              overflowY: "hidden",
              zIndex: 20,
            }}
          >
            <div style={{ color: "rgba(255,255,255,0.9)", fontSize: 18, fontFamily: "monospace", letterSpacing: "0.18em", textTransform: "uppercase", marginBottom: 6, textAlign: "right", paddingRight: 2, fontWeight: 600 }}>
              Open Positions ▸
            </div>
            {openTradesFeed.slice(0, 10).map((p, i) => {
              const isPos = (p.pnlUsd ?? 0) >= 0;
              const botColor = OP_BOT_COLORS[p.bot] ?? "#94a3b8";
              const side = (p.side || "").toLowerCase();
              const isLong  = side === "long"  || side === "buy";
              const isShort = side === "short" || side === "sell";
              const sideLabel = isLong ? "L" : isShort ? "S" : null;
              const sideBg    = isLong ? "rgba(34,197,94,0.18)"  : isShort ? "rgba(239,68,68,0.18)" : "transparent";
              const sideColor = isLong ? "#4ade80"               : isShort ? "#f87171"               : "rgba(148,163,184,0.5)";
              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    padding: "4px 8px",
                    marginBottom: 2,
                    borderRadius: 6,
                    background: isPos ? "rgba(34,197,94,0.07)" : "rgba(239,68,68,0.07)",
                    border: `1px solid ${isPos ? "rgba(34,197,94,0.18)" : "rgba(239,68,68,0.18)"}`,
                    backdropFilter: "blur(10px)",
                  }}
                >
                  {/* col 1 — bot dot */}
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: botColor, flexShrink: 0, boxShadow: `0 0 5px ${botColor}`, marginRight: 6 }} />
                  {/* col 2 — bot icon */}
                  <span style={{ width: 18, fontSize: 13, flexShrink: 0, lineHeight: 1, marginRight: 6 }}>{p.icon}</span>
                  {/* col 3 — symbol (fixed 72px) */}
                  <span style={{ width: 72, fontFamily: "monospace", fontSize: 12, color: "rgba(241,245,249,0.95)", fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 0, marginRight: 4 }}>
                    {p.symbol}
                  </span>
                  {/* col 4 — side badge (fixed 20px) */}
                  <span style={{ width: 20, flexShrink: 0, marginRight: 6 }}>
                    {sideLabel && (
                      <span style={{ fontSize: 8, fontFamily: "monospace", fontWeight: 800, color: sideColor, background: sideBg, borderRadius: 3, padding: "1px 4px" }}>
                        {sideLabel}
                      </span>
                    )}
                  </span>
                  {/* col 5 — position size (flex) */}
                  <span style={{ flex: 1, fontFamily: "monospace", fontSize: 12, fontWeight: 700, color: "rgba(255,255,255,0.9)", whiteSpace: "nowrap", overflow: "hidden" }}>
                    {p.sizeUsd ? fmtOpFull(p.sizeUsd) : ""}
                  </span>
                  {/* col 6 — unrealised P&L (fixed 52px, right-aligned) */}
                  <span style={{ width: 52, fontFamily: "monospace", fontSize: 12, fontWeight: 700, color: isPos ? "#4ade80" : "#f87171", flexShrink: 0, textAlign: "right", marginRight: 4 }}>
                    {(p.pnlUsd ?? 0) >= 0 ? "+" : ""}{fmtOpSize(p.pnlUsd ?? 0)}
                  </span>
                  {/* col 7 — live indicator */}
                  <span style={{ width: 12, fontSize: 9, color: isPos ? "#4ade80" : "#f87171", flexShrink: 0, textAlign: "center" }}>
                    ●
                  </span>
                </div>
              );
            })}
          </div>
        );
      })()}

    </div>
  );
}
