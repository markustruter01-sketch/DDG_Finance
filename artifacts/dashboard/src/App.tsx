import { useEffect, useRef, Suspense } from "react";
import {
  Switch,
  Route,
  Redirect,
  Router as WouterRouter,
  useLocation,
} from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  ClerkProvider,
  useAuth,
  useClerk,
} from "@clerk/react";
import { publishableKeyFromHost } from "@clerk/react/internal";
import { shadcn } from "@clerk/themes";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import NotFound from "@/pages/not-found";
import HomePage from "@/pages/HomePage";
import StreamPage from "@/pages/StreamPage";
import BenchPage from "@/pages/BenchPage";
import Design1Vaudeville from "@/pages/design/Design1Vaudeville";
import Design2Terminal from "@/pages/design/Design2Terminal";
import Design3MissionControl from "@/pages/design/Design3MissionControl";
import Design4Arcade from "@/pages/design/Design4Arcade";
import Design5SpaceFleet from "@/pages/design/Design5SpaceFleet";
import PasskeySignInPage from "@/pages/PasskeySignInPage";
import SecurityPage from "@/pages/SecurityPage";
import { GlobalNav } from "@/components/GlobalNav";
import { RefreshCw } from "lucide-react";
import { usePasskeySession } from "@/hooks/use-passkey-auth";

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

const basePath = import.meta.env.BASE_URL.replace(/\/$/, "");
const clerkPubKey = publishableKeyFromHost(
  window.location.hostname,
  import.meta.env.VITE_CLERK_PUBLISHABLE_KEY,
);
const clerkProxyUrl = import.meta.env.VITE_CLERK_PROXY_URL;

if (!clerkPubKey) {
  throw new Error("Missing VITE_CLERK_PUBLISHABLE_KEY in environment.");
}

const clerkAppearance = {
  theme: shadcn,
  cssLayerName: "clerk",
  options: {
    logoPlacement: "inside" as const,
    logoLinkUrl: basePath || "/",
    logoImageUrl: `${window.location.origin}${basePath}/logo.svg`,
  },
  variables: {
    colorPrimary: "#f2b84b",
    colorForeground: "#f1f5f9",
    colorMutedForeground: "#94a3b8",
    colorDanger: "#f87171",
    colorBackground: "#0b1120",
    colorInput: "#111827",
    colorInputForeground: "#f8fafc",
    colorNeutral: "#334155",
    fontFamily: "'IBM Plex Sans', sans-serif",
    borderRadius: "0.75rem",
  },
  elements: {
    rootBox: "w-full flex justify-center",
    cardBox: "bg-slate-950 rounded-2xl w-[440px] max-w-full overflow-hidden",
    card: "!shadow-none !border-0 !bg-transparent !rounded-none",
    footer: "!shadow-none !border-0 !bg-transparent !rounded-none",
    headerTitle: "text-slate-100",
    headerSubtitle: "text-slate-400",
    socialButtonsBlockButtonText: "text-slate-100",
    formFieldLabel: "text-slate-300",
    footerActionLink: "text-amber-300",
    footerActionText: "text-slate-400",
    dividerText: "text-slate-500",
    identityPreviewEditButton: "text-amber-300",
    formFieldSuccessText: "text-emerald-300",
    alertText: "text-red-200",
    logoBox: "mb-4",
    logoImage: "max-h-10",
    socialButtonsBlockButton: "border-slate-700 bg-slate-900 hover:bg-slate-800",
    formButtonPrimary: "bg-amber-400 text-slate-950 hover:bg-amber-300",
    formFieldInput: "border-slate-700 bg-slate-900 text-slate-100",
    footerAction: "text-slate-400",
    dividerLine: "bg-slate-800",
    alert: "border-red-500/40 bg-red-950/40",
    otpCodeFieldInput: "border-slate-700 bg-slate-900 text-slate-100",
    formFieldRow: "text-slate-100",
    main: "bg-transparent",
  },
};

const CRITICAL_QUERY_KEYS = [
  ["/status/summary"],
  ["/status"],
  ["/health"],
  ["/portfolio"],
  ["/positions/live"],
];

function StreamingLoader() {
  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center">
      <div className="text-center">
        <div className="h-8 w-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <div className="text-xs text-muted-foreground font-mono">Loading Streaming View...</div>
      </div>
    </div>
  );
}

function HomeRoute() {
  const { isLoaded, isSignedIn } = useAuth();
  const passkeySession = usePasskeySession();

  if (!isLoaded || passkeySession.loading) return <StreamingLoader />;
  if (isSignedIn || passkeySession.authenticated) {
    return <Redirect to="/dashboard" />;
  }

  return (
    <PublicLanding />
  );
}

function AuthenticatedRouter() {
  return (
    <>
      <Switch>
        <Route path="/dashboard" component={HomePage} />
        <Route path="/security" component={SecurityPage} />
        <Route path="/home"><Redirect to="/dashboard" /></Route>
        <Route path="/stream">
          <ErrorBoundary label="Stream" autoRecoverMs={2000}>
            <Suspense fallback={<StreamingLoader />}>
              <StreamPage />
            </Suspense>
          </ErrorBoundary>
        </Route>
        <Route path="/bench" component={BenchPage} />
        <Route path="/streaming">
          <Redirect to="/stream?sub=a" />
        </Route>
        <Route path="/streaming-v2">
          <Redirect to="/stream?sub=b" />
        </Route>
        <Route path="/design/1" component={Design1Vaudeville} />
        <Route path="/design/2" component={Design2Terminal} />
        <Route path="/design/3" component={Design3MissionControl} />
        <Route path="/design/4" component={Design4Arcade} />
        <Route path="/design/5" component={Design5SpaceFleet} />
        <Route component={NotFound} />
      </Switch>
      <GlobalNav />
    </>
  );
}

function ProtectedRoute() {
  const { isLoaded, isSignedIn } = useAuth();
  const passkeySession = usePasskeySession();

  if (!isLoaded || passkeySession.loading) return <StreamingLoader />;
  if (isSignedIn || passkeySession.authenticated) return <AuthenticatedRouter />;
  return <Redirect to="/" />;
}

function PublicLanding() {
  return (
    <main className="min-h-screen bg-slate-950 px-6 py-16 text-slate-100">
      <div className="mx-auto flex min-h-[70vh] max-w-3xl flex-col justify-center">
        <div className="mb-5 flex items-center gap-3 text-amber-300">
          <img src={`${basePath}/logo.svg`} alt="" className="h-10 w-10" />
          <span className="font-mono text-xs font-bold tracking-[0.3em]">
            TRADING PLATFORM
          </span>
        </div>
        <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-6xl">
          Fleet Command
        </h1>
        <p className="mt-5 max-w-xl text-lg leading-8 text-slate-400">
          Private operator access for live fleet health, positions, research,
          and audited controls.
        </p>
        <div className="mt-9">
          <a
            href={`${basePath}/sign-in`}
            className="inline-flex items-center rounded-xl bg-amber-400 px-5 py-3 font-semibold text-slate-950 transition hover:bg-amber-300"
          >
            Operator sign in
          </a>
        </div>
      </div>
    </main>
  );
}

function ClerkQueryClientCacheInvalidator() {
  const { addListener } = useClerk();
  const previousUserId = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    const unsubscribe = addListener(({ user }) => {
      const userId = user?.id ?? null;
      if (
        previousUserId.current !== undefined &&
        previousUserId.current !== userId
      ) {
        queryClient.clear();
      }
      previousUserId.current = userId;
    });
    return unsubscribe;
  }, [addListener]);

  return null;
}

function ClerkProviderWithRoutes() {
  const [, setLocation] = useLocation();

  return (
    <ClerkProvider
      publishableKey={clerkPubKey}
      proxyUrl={clerkProxyUrl}
      appearance={clerkAppearance}
      signInUrl={`${basePath}/sign-in`}
      localization={{
        signIn: {
          start: {
            title: "Welcome back, operator",
            subtitle: "Sign in to access Fleet Command",
          },
        },
        signUp: {
          start: {
            title: "Create an operator account",
            subtitle: "Set up private Fleet Command access",
          },
        },
      }}
      routerPush={(to) => setLocation(stripBase(to))}
      routerReplace={(to) => setLocation(stripBase(to), { replace: true })}
    >
      <QueryClientProvider client={queryClient}>
        <ClerkQueryClientCacheInvalidator />
        <VisibilityRefetcher />
        <TooltipProvider>
          <Switch>
            <Route
              path="/sign-in/*?"
              component={() => <PasskeySignInPage basePath={basePath} />}
            />
            <Route path="/" component={HomeRoute} />
            <Route component={ProtectedRoute} />
          </Switch>
          <Toaster />
        </TooltipProvider>
      </QueryClientProvider>
    </ClerkProvider>
  );
}

function stripBase(path: string): string {
  return basePath && path.startsWith(basePath)
    ? path.slice(basePath.length) || "/"
    : path;
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
    <ErrorBoundary fallback={<AppCrashFallback />} label="App" autoRecoverMs={3000}>
      <VisibilityContext.Provider value={isVisible}>
        <WouterRouter base={basePath}>
          <ClerkProviderWithRoutes />
        </WouterRouter>
      </VisibilityContext.Provider>
    </ErrorBoundary>
  );
}

export default App;
