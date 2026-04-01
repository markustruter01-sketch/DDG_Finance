import { useEffect } from "react";
import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import NotFound from "@/pages/not-found";
import Dashboard from "@/pages/Dashboard";
import { RefreshCw } from "lucide-react";
import { VisibilityContext, useVisibilityProvider, installVisibilityListener } from "@/hooks/use-visibility";

installVisibilityListener();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 60_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      refetchIntervalInBackground: false,
    },
  },
});

const CRITICAL_QUERY_KEYS = [
  ["/status/summary"],
  ["/status"],
  ["/health"],
  ["/portfolio"],
  ["/positions/live"],
];

function Router() {
  return (
    <Switch>
      <Route path="/" component={Dashboard} />
      <Route component={NotFound} />
    </Switch>
  );
}

function AppCrashFallback() {
  return (
    <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center gap-6 text-center px-6">
      <div className="h-12 w-12 rounded-2xl bg-red-500/10 border border-red-500/30 flex items-center justify-center">
        <RefreshCw className="h-6 w-6 text-red-400" />
      </div>
      <div>
        <h1 className="text-xl font-bold text-white mb-2">Something went wrong</h1>
        <p className="text-sm text-slate-400 max-w-sm">
          The dashboard encountered an unexpected error. Your positions and data are safe — this is a display issue only.
        </p>
      </div>
      <button
        onClick={() => window.location.reload()}
        className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary/20 border border-primary/40 text-primary text-sm font-semibold hover:bg-primary/30 transition-all"
      >
        <RefreshCw className="h-4 w-4" /> Reload Dashboard
      </button>
    </div>
  );
}

function VisibilityRefetcher() {
  useEffect(() => {
    const handler = () => {
      if (document.visibilityState === "visible") {
        for (const key of CRITICAL_QUERY_KEYS) {
          queryClient.refetchQueries({ queryKey: key });
        }
      }
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, []);
  return null;
}

function App() {
  const isVisible = useVisibilityProvider();

  return (
    <ErrorBoundary fallback={<AppCrashFallback />} label="App">
      <VisibilityContext.Provider value={isVisible}>
        <QueryClientProvider client={queryClient}>
          <VisibilityRefetcher />
          <TooltipProvider>
            <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
              <Router />
            </WouterRouter>
            <Toaster />
          </TooltipProvider>
        </QueryClientProvider>
      </VisibilityContext.Provider>
    </ErrorBoundary>
  );
}

export default App;
