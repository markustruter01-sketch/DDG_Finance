/**
 * App.tsx — AlgoEdge SaaS Platform (System B)
 *
 * Route map:
 *   /saas/           → Home (Stage 4 content)
 *   /saas/dashboard  → Insight Dashboard (Stage 4 content)
 *   /saas/settings   → Connect Your Exchange (Stage 4 content)
 *
 * All routes share the persistent Shell (navbar + dev banner + footer).
 * Routing is nested under BASE_URL (/saas/) via Wouter's base prop.
 */

import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BASE_URL } from "@/lib/config";
import Shell from "@/components/layout/Shell";
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
    <Shell>
      <Switch>
        <Route path="/">
          <Placeholder stage={4} name="AlgoEdge — Home" />
        </Route>

        <Route path="/dashboard">
          <Placeholder stage={4} name="Insight Dashboard" />
        </Route>

        <Route path="/settings">
          <Placeholder stage={4} name="Connect Your Exchange" />
        </Route>

        <Route>
          <Placeholder stage={0} name="Page not found" />
        </Route>
      </Switch>
    </Shell>
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
