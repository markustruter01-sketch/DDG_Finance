import { motion } from "framer-motion";
import { useVault, useForexVault, useKrakenPerformance } from "@/hooks/use-trading";

function formatUsd(n: number | undefined | null): string {
  if (n == null) return "$0";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function formatUsdPrecise(n: number | undefined | null): string {
  if (n == null || n === 0) return "+$0";
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function VaultDisplay() {
  const { data: vault } = useVault();
  const { data: fxVault } = useForexVault();
  const djPerf = useKrakenPerformance("davy-jones");
  const bbPerf = useKrakenPerformance("blackbeard");
  const caPerf = useKrakenPerformance("calypso");

  const combinedVault = vault?.total_vaulted_usd ?? 0;
  const forexVault = fxVault?.vault_total_usd ?? 0;

  const cryptoPnl = (djPerf.data?.total_pnl_usd ?? 0) + (bbPerf.data?.total_pnl_usd ?? 0) + (caPerf.data?.total_pnl_usd ?? 0);
  const cryptoVault = Math.max(0, cryptoPnl * 0.20);
  const oracleVault = Math.max(0, combinedVault - cryptoVault);

  const totalVaulted = combinedVault + forexVault;
  const totalSweeps = (vault?.total_sweeps ?? 0) + (fxVault?.sweeps?.length ?? 0);
  const vaulted24h = vault?.vaulted_24h ?? 0;

  return (
    <div className="flex flex-col gap-1.5 flex-1 min-h-0">
      <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "rgba(52,211,153,0.5)" }}>Growth Vault</div>
      <div className="rounded-lg border border-emerald-500/20 bg-emerald-950/10 px-2.5 py-2 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent" />
        <div className="relative flex items-center gap-2">
          <span className="text-[14px]">🏦</span>
          <div className="flex-1">
            <div className="text-[7px] uppercase tracking-widest font-bold" style={{ color: "rgba(52,211,153,0.6)" }}>Total Vaulted</div>
            <div className="flex items-baseline gap-2">
              <motion.div
                className="text-[18px] font-mono font-black"
                style={{ color: "#34d399", textShadow: "0 0 20px rgba(16,185,129,0.6), 0 0 40px rgba(16,185,129,0.3)" }}
                animate={{ opacity: [0.6, 1, 0.6], scale: [0.98, 1.02, 0.98] }}
                transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
              >
                {formatUsd(totalVaulted)}
              </motion.div>
              {vaulted24h > 0 && (
                <span
                  className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded"
                  style={{
                    color: "#4ade80",
                    backgroundColor: "rgba(74,222,128,0.1)",
                    border: "1px solid rgba(74,222,128,0.2)",
                  }}
                >
                  {formatUsdPrecise(vaulted24h)} <span style={{ color: "rgba(74,222,128,0.6)" }}>today</span>
                </span>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[7px] uppercase tracking-widest font-bold" style={{ color: "rgba(52,211,153,0.6)" }}>Sweeps</div>
            <motion.div
              className="text-[16px] font-mono font-black"
              style={{ color: "#34d399", textShadow: "0 0 16px rgba(16,185,129,0.5), 0 0 32px rgba(16,185,129,0.25)" }}
              animate={{ opacity: [0.7, 1, 0.7], scale: [0.98, 1.02, 0.98] }}
              transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
            >
              {totalSweeps}
            </motion.div>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-emerald-500/10 bg-emerald-950/5 px-3 py-2.5 flex-1 flex items-center">
        <div className="text-[14px] font-mono leading-[1.75]" style={{ color: "rgba(52,211,153,0.55)" }}>
          Every winning trade contributes{" "}
          <span className="font-black" style={{ color: "rgba(52,211,153,0.9)" }}>20%</span>{" "}
          of its realised profit to the{" "}
          <span className="font-black" style={{ color: "rgba(52,211,153,0.9)" }}>Growth Vault</span>
          {" "}— automatically, across all bots. Oracle, Davy Jones, Blackbeard, Calypso, and Navigator all feed the vault in real time. Capital compounds here, isolated from active trading risk.
        </div>
      </div>
    </div>
  );
}
