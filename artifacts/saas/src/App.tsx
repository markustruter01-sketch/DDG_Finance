/**
 * App.tsx — AlgoEdge SaaS Platform (System B)
 *
 * Provider order (outermost → innermost):
 *   QueryClientProvider  — React Query cache
 *   WouterRouter         — path-based routing under /saas/
 *   AuthProvider         — session state (reads /saas-api/auth/me)
 *   Shell                — navbar, dev banner, login gate, footer
 *   Routes               — page content
 *
 * Route map:
 *   /saas/           → Home (Stage 4 content)
 *   /saas/dashboard  → Insight Dashboard (Stage 4 content)
 *   /saas/settings   → Connect Your Exchange (Stage 4 content)
 */

import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BASE_URL } from "@/lib/config";
import { AuthProvider } from "@/context/AuthContext";
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

function Routes() {
  return (
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
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WouterRouter base={BASE_URL.replace(/\/$/, "")}>
        <AuthProvider>
          <Shell>
            <Routes />
          </Shell>
        </AuthProvider>
      </WouterRouter>
    </QueryClientProvider>
  );
}
