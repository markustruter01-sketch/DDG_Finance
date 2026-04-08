import { Radio } from "lucide-react";

export default function StreamPage() {
  return (
    <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center gap-4 text-center px-6">
      <div className="h-14 w-14 rounded-2xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center">
        <Radio className="h-7 w-7 text-rose-400" />
      </div>
      <div>
        <h1 className="text-xl font-bold text-white mb-2">Stream</h1>
        <p className="text-sm text-slate-400">Building…</p>
      </div>
    </div>
  );
}
