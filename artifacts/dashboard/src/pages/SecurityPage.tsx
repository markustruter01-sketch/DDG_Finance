import { useEffect, useState } from "react";
import { Fingerprint, KeyRound, Loader2, Trash2 } from "lucide-react";
import {
  deletePasskey,
  listPasskeys,
  registerPasskey,
} from "@/hooks/use-passkey-auth";

type Credential = Awaited<ReturnType<typeof listPasskeys>>[number];

function formatDate(value: string | null): string {
  if (!value) return "Not used yet";
  return new Date(value).toLocaleString();
}

export default function SecurityPage() {
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadCredentials() {
    setLoading(true);
    try {
      setCredentials(await listPasskeys());
    } catch {
      setError("Unable to load registered devices.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCredentials();
  }, []);

  async function handleRegister() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await registerPasskey();
      setMessage("This device is now registered for biometric sign-in.");
      await loadCredentials();
    } catch (cause: any) {
      setError(
        cause?.response?.data?.detail ||
          (cause instanceof Error ? cause.message : "Device registration failed."),
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm("Remove this device passkey? You may need recovery sign-in to return.")) {
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await deletePasskey(id);
      setCredentials((current) => current.filter((credential) => credential.id !== id));
      setMessage("Device passkey removed.");
    } catch (cause: any) {
      setError(
        cause?.response?.data?.detail ||
          (cause instanceof Error ? cause.message : "Unable to remove this device."),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 px-4 pb-32 pt-10 text-slate-100 sm:px-8">
      <div className="mx-auto max-w-3xl">
        <div className="mb-8">
          <div className="flex items-center gap-3 text-amber-300">
            <KeyRound className="h-5 w-5" />
            <span className="font-mono text-xs font-bold tracking-[0.24em]">
              SECURITY
            </span>
          </div>
          <h1 className="mt-3 text-3xl font-bold tracking-tight">Device access</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
            Register a passkey to use Face ID, Touch ID, Windows Hello, or a
            security key instead of a memorised password.
          </p>
        </div>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
            <div>
              <h2 className="font-semibold text-slate-100">Register this device</h2>
              <p className="mt-1 text-sm text-slate-400">
                Your device will ask for its local biometric verification.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void handleRegister()}
              disabled={busy}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-amber-400 px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-amber-300 disabled:cursor-wait disabled:opacity-60"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Fingerprint className="h-4 w-4" />}
              {busy ? "Waiting…" : "Add biometric passkey"}
            </button>
          </div>
        </section>

        {(error || message) && (
          <div
            role={error ? "alert" : "status"}
            className={`mt-4 rounded-xl border px-4 py-3 text-sm ${
              error
                ? "border-red-500/30 bg-red-950/30 text-red-200"
                : "border-emerald-500/30 bg-emerald-950/30 text-emerald-200"
            }`}
          >
            {error || message}
          </div>
        )}

        <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <h2 className="font-semibold text-slate-100">Registered devices</h2>
          {loading ? (
            <div className="flex items-center gap-2 py-8 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading devices…
            </div>
          ) : credentials.length === 0 ? (
            <p className="py-8 text-sm text-slate-500">
              No passkeys are registered yet. Add this device above.
            </p>
          ) : (
            <div className="mt-4 space-y-3">
              {credentials.map((credential) => (
                <div
                  key={credential.id}
                  className="flex items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <Fingerprint className="h-5 w-5 shrink-0 text-amber-300" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-slate-200">
                        {credential.label}
                      </p>
                      <p className="text-xs text-slate-500">
                        Added {formatDate(credential.created_at)} · Last used{" "}
                        {formatDate(credential.last_used_at)}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleDelete(credential.id)}
                    disabled={busy}
                    aria-label={`Remove ${credential.label}`}
                    className="rounded-lg p-2 text-slate-500 transition hover:bg-red-950/40 hover:text-red-300 disabled:opacity-50"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
