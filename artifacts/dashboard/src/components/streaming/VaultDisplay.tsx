import { motion } from "framer-motion";
import { useVault, useForexVault } from "@/hooks/use-trading";

function formatUsd(n: number | undefined | null): string {
  if (n == null) return "$0";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

export function VaultDisplay() {
  const { data: vault } = useVault();
  const { data: fxVault } = useForexVault();

  const oracleVault = vault?.total_vaulted_usd ?? 0;
  const forexVault = fxVault?.vault_total_usd ?? 0;
  const totalVaulted = oracleVault + forexVault;
  const totalSweeps = (vault?.total_sweeps ?? 0) + (fxVault?.sweeps?.length ?? 0);

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[9px] uppercase tracking-widest text-emerald-400/50 font-bold">Capital Vault</div>
      <div className="rounded-xl border border-emerald-500/20 bg-emerald-950/10 p-3 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent" />
        <div className="relative">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">🏦</span>
            <span className="text-[8px] uppercase tracking-widest text-emerald-400/60 font-bold">Total Vaulted</span>
          </div>
          <motion.div
            className="text-2xl font-mono font-black text-emerald-400"
            style={{ textShadow: "0 0 15px rgba(16,185,129,0.5)" }}
            animate={{ opacity: [0.8, 1, 0.8] }}
            transition={{ duration: 3, repeat: Infinity }}
          >
            {formatUsd(totalVaulted)}
          </motion.div>
          <div className="text-[9px] text-emerald-400/40 font-mono mt-1">
            {totalSweeps} sweep{totalSweeps !== 1 ? "s" : ""} completed
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-yellow-500/15 bg-yellow-950/10 p-2">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-[10px]">🔮</span>
            <span className="text-[7px] uppercase tracking-widest text-yellow-400/50 font-bold">Oracle Vault</span>
          </div>
          <div className="text-xs font-mono font-bold text-yellow-400/80">{formatUsd(oracleVault)}</div>
        </div>
        <div className="rounded-lg border border-teal-500/15 bg-teal-950/10 p-2">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-[10px]">🧭</span>
            <span className="text-[7px] uppercase tracking-widest text-teal-400/50 font-bold">Forex Vault</span>
          </div>
          <div className="text-xs font-mono font-bold text-teal-400/80">{formatUsd(forexVault)}</div>
        </div>
      </div>
    </div>
  );
}
