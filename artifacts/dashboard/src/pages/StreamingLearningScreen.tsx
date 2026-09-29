import { useFleetEquity } from "@/hooks/use-portfolio";

const lessons = [
  ["Fleet totals", "This view reads fleet totals from /fleet/equity. Missing values stay unavailable instead of being reconstructed here."],
  ["Bot identity", "Known bot IDs use canonical labels. Journal rows without a bot ID remain unattributed."],
  ["Read-only view", "These notes summarize operational data. This page does not edit strategy or risk settings."],
];

export default function StreamingLearningScreen() {
  const { data } = useFleetEquity();
  const total = data?.fleet_total;
  return (
    <section className="stream-screen stream-screen-learning h-full overflow-auto bg-slate-950 p-6 text-white font-mono">
      <div className="mx-auto max-w-4xl">
        <div className="text-xs tracking-[0.3em] text-cyan-300">FLEET NOTES</div>
        <h1 className="mt-2 text-3xl font-black">Current operating notes</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-400">A read-only summary of the registry, fleet metrics, and data attribution available to this dashboard.</p>
        <div className="mt-6 grid gap-3 md:grid-cols-3">
          {lessons.map(([title, text]) => <article key={title} className="rounded-xl border border-cyan-400/20 bg-slate-900/70 p-4"><h2 className="text-sm font-bold text-cyan-200">{title}</h2><p className="mt-3 text-xs leading-5 text-slate-300">{text}</p></article>)}
        </div>
        <div className="mt-6 rounded-xl border border-violet-400/20 bg-violet-950/20 p-4 text-xs">
           FLEET TOTAL <strong className="ml-2 text-lg text-white">{total?.equity != null ? `$${Math.round(total.equity).toLocaleString()}` : "—"}</strong>
        </div>
      </div>
    </section>
  );
}