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
 *   /saas/           → Home     (landing page)
 *   /saas/dashboard  → Dashboard (live insight data + 1-click execution)
 *   /saas/pricing    → Pricing  (Stripe checkout — 3-tier)
 *   /saas/settings   → Settings (exchange API key management + live mode toggle)
 */

import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BASE_URL } from "@/lib/config";
import { AuthProvider } from "@/context/AuthContext";
import Shell from "@/components/layout/Shell";
import Home from "@/pages/Home";
import Dashboard from "@/pages/Dashboard";
import Pricing from "@/pages/Pricing";
import Settings from "@/pages/Settings";
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
      <Route path="/" component={Home} />
      <Route path="/dashboard" component={Dashboard} />
      <Route path="/pricing" component={Pricing} />
      <Route path="/settings" component={Settings} />
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
