import { useEffect } from "react";
import { Switch, Route, Redirect, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import NotFound from "@/pages/not-found";
import HomePage from "@/pages/HomePage";
import BenchPage from "@/pages/BenchPage";
import ControlsPage from "@/pages/ControlsPage";
import ForexPage from "@/pages/ForexPage";
import LeaguePage from "@/pages/LeaguePage";
import MePage from "@/pages/MePage";
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
      <Route path="/" component={HomePage} />
      <Route path="/home"><Redirect to="/" /></Route>
      <Route path="/bench" component={BenchPage} />
      <Route path="/controls" component={ControlsPage} />
      <Route path="/forex" component={ForexPage} />
      <Route path="/league" component={LeaguePage} />
      <Route path="/me" component={MePage} />
      <Route component={NotFound} />
    </Switch>
  );
}

function AppCrashFallback() {
  return (
    <div className="ng-page dusk">
      <main className="crash glass panel">
        <h1 className="heading">Something went wrong</h1>
        <p className="body" style={{ margin: 0 }}>
          The dashboard hit an unexpected error. Positions and data are safe: this is a display problem only.
        </p>
        <div><button className="btn fill" onClick={() => window.location.reload()}>
          <RefreshCw size={15} aria-hidden="true" /> Reload dashboard
        </button></div>
      </main>
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
    <ErrorBoundary fallback={<AppCrashFallback />} label="App" autoRecoverMs={3000}>
      <VisibilityContext.Provider value={isVisible}>
        <QueryClientProvider client={queryClient}>
          <VisibilityRefetcher />
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
            <Router />
          </WouterRouter>
        </QueryClientProvider>
      </VisibilityContext.Provider>
    </ErrorBoundary>
  );
}

export default App;
