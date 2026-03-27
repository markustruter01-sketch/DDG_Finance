import { useState } from "react";
import { Card, CardHeader, CardTitle, CardContent, Button, Modal } from "./ui";
import { useRunAnalysis, useTripKillSwitch, useResetKillSwitch, useRunPostMortem } from "@/hooks/use-trading";
import { Loader2, AlertTriangle, ShieldCheck, Play, RefreshCw, Activity } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

export function ControlPanel() {
  const { toast } = useToast();
  
  const runAnalysis = useRunAnalysis();
  const tripKillSwitch = useTripKillSwitch();
  const resetKillSwitch = useResetKillSwitch();
  const runPostMortem = useRunPostMortem();

  const [activeModal, setActiveModal] = useState<"live-run" | "kill-switch" | "reset-kill" | null>(null);
  const [lastResult, setLastResult] = useState<any>(null);

  const handleAction = async (action: () => Promise<any>, successMsg: string) => {
    setActiveModal(null);
    try {
      const res = await action();
      setLastResult(res);
      toast({ title: successMsg, description: "Check response block below for details." });
    } catch (err: any) {
      toast({ variant: "destructive", title: "Action Failed", description: err.message });
      setLastResult({ error: err.message });
    }
  };

  return (
    <Card className="col-span-full border-primary/20 shadow-[0_0_30px_rgba(59,130,246,0.05)] overflow-hidden relative">
      <div className="absolute top-0 right-0 w-64 h-64 bg-primary/5 rounded-full blur-3xl -z-10 translate-x-1/2 -translate-y-1/2" />
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-primary" />
          Mission Control
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex flex-wrap gap-4">
          <Button 
            variant="outline" 
            className="border-primary/50 hover:bg-primary/10 text-primary"
            disabled={runAnalysis.isPending}
            onClick={() => handleAction(() => runAnalysis.mutateAsync({ dry_run: true, force: true }), "Dry Run Complete")}
          >
            {runAnalysis.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
            Run Analysis (Dry Run)
          </Button>
          
          <Button 
            variant="success"
            disabled={runAnalysis.isPending}
            onClick={() => setActiveModal("live-run")}
          >
            <Play className="mr-2 h-4 w-4 fill-current" />
            Run Analysis (LIVE)
          </Button>

          <Button 
            variant="default"
            disabled={runPostMortem.isPending}
            onClick={() => handleAction(() => runPostMortem.mutateAsync(), "Post-Mortem Complete")}
            className="bg-slate-700 text-white hover:bg-slate-600 shadow-none"
          >
            {runPostMortem.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            Run Post-Mortem
          </Button>

          <div className="flex-1" />

          <Button 
            variant="outline"
            className="border-amber-500/50 hover:bg-amber-500/10 text-amber-500"
            disabled={resetKillSwitch.isPending}
            onClick={() => setActiveModal("reset-kill")}
          >
            <ShieldCheck className="mr-2 h-4 w-4" />
            Reset Kill Switch
          </Button>

          <Button 
            variant="danger"
            disabled={tripKillSwitch.isPending}
            onClick={() => setActiveModal("kill-switch")}
          >
            <AlertTriangle className="mr-2 h-4 w-4 fill-current" />
            Trip Kill Switch
          </Button>
        </div>

        {lastResult && (
          <div className="mt-4 rounded-xl border border-white/10 bg-black/50 p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-mono text-muted-foreground uppercase">Response Output</span>
              <button onClick={() => setLastResult(null)} className="text-xs hover:text-white text-muted-foreground">Clear</button>
            </div>
            <pre className="text-xs font-mono text-emerald-400/90 overflow-x-auto p-2 bg-slate-950 rounded-lg border border-white/5">
              {JSON.stringify(lastResult, null, 2)}
            </pre>
          </div>
        )}
      </CardContent>

      {/* Modals */}
      <Modal isOpen={activeModal === "live-run"} onClose={() => setActiveModal(null)} title="Confirm Live Execution">
        <p className="text-muted-foreground mb-6">
          This will execute real paper trades against Alpaca and modify your portfolio. Are you sure you want to proceed with a LIVE run?
        </p>
        <div className="flex justify-end gap-3">
          <Button variant="outline" onClick={() => setActiveModal(null)}>Cancel</Button>
          <Button variant="success" onClick={() => handleAction(() => runAnalysis.mutateAsync({ dry_run: false, force: true }), "Live Run Completed")}>
            Execute Live Run
          </Button>
        </div>
      </Modal>

      <Modal isOpen={activeModal === "kill-switch"} onClose={() => setActiveModal(null)} title="⚠️ Trip Kill Switch?">
        <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive mb-6">
          <p className="font-bold flex items-center gap-2 mb-2"><AlertTriangle className="h-5 w-5" /> DANGER</p>
          <p className="text-sm">Tripping the kill switch will IMMEDIATELY liquidate all open positions via market orders and halt all future trading for the day.</p>
        </div>
        <div className="flex justify-end gap-3">
          <Button variant="outline" onClick={() => setActiveModal(null)}>Cancel</Button>
          <Button variant="danger" onClick={() => handleAction(() => tripKillSwitch.mutateAsync(), "Kill Switch Tripped")}>
            LIQUIDATE EVERYTHING
          </Button>
        </div>
      </Modal>

      <Modal isOpen={activeModal === "reset-kill"} onClose={() => setActiveModal(null)} title="Reset Kill Switch">
        <p className="text-muted-foreground mb-6">
          This will clear the tripped status and capture current equity as the new opening baseline for the day's drawdown calculations.
        </p>
        <div className="flex justify-end gap-3">
          <Button variant="outline" onClick={() => setActiveModal(null)}>Cancel</Button>
          <Button onClick={() => handleAction(() => resetKillSwitch.mutateAsync({}), "Kill Switch Reset")}>
            Confirm Reset
          </Button>
        </div>
      </Modal>

    </Card>
  );
}
