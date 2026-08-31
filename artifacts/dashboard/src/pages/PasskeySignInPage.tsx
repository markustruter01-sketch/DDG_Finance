import { useState } from "react";
import { Fingerprint, ShieldCheck } from "lucide-react";
import { SignIn } from "@clerk/react";
import { signInWithPasskey } from "@/hooks/use-passkey-auth";

type PasskeySignInPageProps = {
  basePath: string;
};

export default function PasskeySignInPage({ basePath }: PasskeySignInPageProps) {
  const [busy, setBusy] = useState(false);
  const [showRecovery, setShowRecovery] = useState(false);
  const [error, setError] = useState("");

  async function handlePasskeySignIn() {
    setBusy(true);
    setError("");
    try {
      await signInWithPasskey();
      window.location.assign(`${basePath}/dashboard`);
    } catch (cause: any) {
      const detail = cause?.response?.data?.detail;
      setError(
        typeof detail === "string"
          ? detail
          : cause instanceof Error
            ? cause.message
            : "Device sign-in failed. Use recovery sign-in to set up this device.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[100dvh] bg-slate-950 px-4 py-12 text-slate-100">
      <div className="mx-auto flex min-h-[80dvh] max-w-md flex-col justify-center">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl border border-amber-300/30 bg-amber-300/10">
            <Fingerprint className="h-7 w-7 text-amber-300" />
          </div>
          <p className="font-mono text-xs font-bold tracking-[0.28em] text-amber-300">
            FLEET COMMAND
          </p>
          <h1 className="mt-3 text-3xl font-bold tracking-tight">Operator access</h1>
          <p className="mt-3 text-sm leading-6 text-slate-400">
            Use your device biometric prompt to unlock the trading dashboard.
            Your private passkey never leaves this device.
          </p>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl shadow-black/20">
          <button
            type="button"
            onClick={() => void handlePasskeySignIn()}
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-amber-400 px-4 py-3 font-semibold text-slate-950 transition hover:bg-amber-300 disabled:cursor-wait disabled:opacity-60"
          >
            <Fingerprint className="h-5 w-5" />
            {busy ? "Waiting for your device…" : "Continue with Face ID / biometrics"}
          </button>

          <div className="mt-4 flex items-start gap-2 text-xs leading-5 text-slate-500">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
            <span>
              Your browser may show Touch ID, Face ID, Windows Hello, or a
              security-key prompt.
            </span>
          </div>

          {error && (
            <div
              role="alert"
              className="mt-4 rounded-xl border border-red-500/30 bg-red-950/30 px-3 py-2 text-sm text-red-200"
            >
              {error}
            </div>
          )}

          <button
            type="button"
            onClick={() => setShowRecovery((current) => !current)}
            className="mt-6 w-full text-center text-xs font-semibold text-slate-400 underline decoration-slate-700 underline-offset-4 transition hover:text-amber-300"
          >
            {showRecovery ? "Hide recovery sign-in" : "First time here? Use recovery sign-in"}
          </button>

          {showRecovery && (
            <div className="mt-6 border-t border-slate-800 pt-6">
              <p className="mb-4 text-center text-xs leading-5 text-slate-500">
                Sign in once to register this device under Security.
              </p>
              <SignIn
                routing="path"
                path={`${basePath}/sign-in`}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
