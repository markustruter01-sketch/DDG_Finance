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

  const oracleVault = vault?.total_vaulted_usd ?? 0;
  const forexVault = fxVault?.vault_total_usd ?? 0;

  const cryptoPnl = (djPerf.data?.total_pnl_usd ?? 0) + (bbPerf.data?.total_pnl_usd ?? 0) + (caPerf.data?.total_pnl_usd ?? 0);
  const cryptoVault = Math.max(0, cryptoPnl * 0.20);

  const totalVaulted = oracleVault + forexVault + cryptoVault;
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
              animate={{ opacity: [0.8, 1, 0.8] }}
              transition={{ duration: 3, repeat: Infinity }}
            >
              {formatUsd(totalVaulted)}
            </motion.div>
          </div>
          <div className="text-[9px] text-emerald-400/50 font-mono font-bold">{totalSweeps} sweeps</div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-1.5">
        <div className="rounded-lg border border-yellow-500/15 bg-yellow-950/10 px-2 py-1.5">
          <div className="flex items-center gap-1 mb-0.5">
            <span className="text-[9px]">🔮</span>
            <span className="text-[7px] uppercase tracking-widest text-yellow-400/50 font-bold">Oracle</span>
          </div>
          <div className="text-[11px] font-mono font-bold text-yellow-400/80">{formatUsd(oracleVault)}</div>
        </div>
        <div className="rounded-lg border border-cyan-500/15 bg-cyan-950/10 px-2 py-1.5">
          <div className="flex items-center gap-1 mb-0.5">
            <span className="text-[9px]">⚓</span>
            <span className="text-[7px] uppercase tracking-widest text-cyan-400/50 font-bold">Crypto</span>
          </div>
          <div className="text-[11px] font-mono font-bold text-cyan-400/80">{formatUsd(cryptoVault)}</div>
        </div>
        <div className="rounded-lg border border-teal-500/15 bg-teal-950/10 px-2 py-1.5">
          <div className="flex items-center gap-1 mb-0.5">
            <span className="text-[9px]">🧭</span>
            <span className="text-[7px] uppercase tracking-widest text-teal-400/50 font-bold">Forex</span>
          </div>
          <div className="text-[11px] font-mono font-bold text-teal-400/80">{formatUsd(forexVault)}</div>
        </div>
      </div>

      <div className="rounded-lg border border-emerald-500/10 bg-emerald-950/5 px-2.5 py-2">
        <div className="text-[8px] font-mono text-emerald-400/40 leading-relaxed">
          20% of realized profits are automatically swept into the <span className="text-emerald-400/70 font-bold">Growth Vault (JEPQ)</span> for compounding high-yield dividend income.
        </div>
      </div>
    </div>
  );
}
