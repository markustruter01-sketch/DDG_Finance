/**
 * App.tsx — AlgoEdge SaaS Platform (System B)
 *
 * Route map (stages build these out):
 *   /saas/          → Home / landing (Stage 2 adds nav, Stage 4 replaces content)
 *   /saas/dashboard → Main insight dashboard (Stage 4)
 *   /saas/settings  → API key plug-in page (Stage 4)
 *
 * All routes are nested under BASE_URL (/saas/) via Wouter's base prop.
 */

import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BASE_URL } from "@/lib/config";
import Placeholder from "@/pages/Placeholder";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

function Router() {
  return (
    <Switch>
      {/* Stage 4: replaced by the real Home / landing */}
      <Route path="/">
        <Placeholder stage={2} name="AlgoEdge — Home" />
      </Route>

      {/* Stage 4: Main insight dashboard */}
      <Route path="/dashboard">
        <Placeholder stage={4} name="Insight Dashboard" />
      </Route>

      {/* Stage 4: API key plug-in settings page */}
      <Route path="/settings">
        <Placeholder stage={4} name="Connect Your Exchange" />
      </Route>

      {/* Catch-all */}
      <Route>
        <Placeholder stage={0} name="Page not found" />
      </Route>
    </Switch>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WouterRouter base={BASE_URL.replace(/\/$/, "")}>
        <Router />
      </WouterRouter>
    </QueryClientProvider>
  );
}
