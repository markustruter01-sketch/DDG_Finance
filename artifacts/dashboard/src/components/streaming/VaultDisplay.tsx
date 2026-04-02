import { motion } from "framer-motion";
import { useVault, useForexVault, useKrakenPerformance } from "@/hooks/use-trading";

function formatUsd(n: number | undefined | null): string {
  if (n == null) return "$0";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
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

  return (
    <div className="flex flex-col gap-1.5 flex-1 min-h-0">
      <div className="text-[9px] uppercase tracking-widest text-emerald-400/50 font-bold">Growth Vault</div>
      <div className="rounded-lg border border-emerald-500/20 bg-emerald-950/10 px-3 py-3 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent" />
        <div className="relative flex items-center gap-3">
          <span className="text-xl">🏦</span>
          <div className="flex-1">
            <div className="text-[7px] uppercase tracking-widest text-emerald-400/60 font-bold">Total Vaulted</div>
            <motion.div
              className="text-2xl font-mono font-black text-emerald-400"
              style={{ textShadow: "0 0 20px rgba(16,185,129,0.6), 0 0 40px rgba(16,185,129,0.3)" }}
              animate={{ opacity: [0.6, 1, 0.6], scale: [0.98, 1.02, 0.98] }}
              transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
            >
              {formatUsd(totalVaulted)}
            </motion.div>
          </div>
          <div className="text-[9px] text-emerald-400/50 font-mono font-bold">{totalSweeps} sweeps</div>
        </div>
      </div>

      <div className="rounded-lg border border-emerald-500/10 bg-emerald-950/5 px-3 py-3 flex-1">
        <div className="text-[13px] font-mono text-emerald-400/50 leading-relaxed">
          20% of realized profits are automatically swept into the <span className="text-emerald-400/80 font-bold">Growth Vault (JEPQ)</span> for compounding high-yield dividend income. This passive dividend income is then re-invested into the platform in order to accelerate exponential growth.
        </div>
      </div>
    </div>
  );
}
