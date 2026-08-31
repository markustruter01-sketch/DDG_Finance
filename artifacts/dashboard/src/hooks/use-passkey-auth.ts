import { useCallback, useEffect, useState } from "react";
import { api } from "@/hooks/use-trading-client";

type PasskeySession = {
  authenticated: boolean;
  user_id?: string;
};

type PasskeyCredentialSummary = {
  id: string;
  label: string;
  created_at: string | null;
  last_used_at: string | null;
};

function decodeBase64Url(value: string): ArrayBuffer {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = window.atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return bytes.buffer;
}

function encodeBase64Url(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return window
    .btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function supportsPasskeys(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator.credentials?.get === "function" &&
    typeof navigator.credentials?.create === "function"
  );
}

function serializeCredential(credential: Credential): Record<string, unknown> {
  const publicKeyCredential = credential as PublicKeyCredential;
  const response = publicKeyCredential.response;
  const payload: Record<string, unknown> = {
    id: publicKeyCredential.id,
    rawId: encodeBase64Url(publicKeyCredential.rawId),
    type: publicKeyCredential.type,
    clientExtensionResults: publicKeyCredential.getClientExtensionResults(),
  };

  if ("attestationObject" in response) {
    const attestation = response as AuthenticatorAttestationResponse;
    payload.response = {
      clientDataJSON: encodeBase64Url(attestation.clientDataJSON),
      attestationObject: encodeBase64Url(attestation.attestationObject),
      transports: attestation.getTransports?.() ?? [],
    };
  } else {
    const assertion = response as AuthenticatorAssertionResponse;
    payload.response = {
      clientDataJSON: encodeBase64Url(assertion.clientDataJSON),
      authenticatorData: encodeBase64Url(assertion.authenticatorData),
      signature: encodeBase64Url(assertion.signature),
      userHandle: assertion.userHandle ? encodeBase64Url(assertion.userHandle) : null,
    };
  }

  return payload;
}

function registrationOptionsForBrowser(
  options: Record<string, unknown>,
): PublicKeyCredentialCreationOptions {
  const user = options.user as Record<string, unknown>;
  const excludeCredentials = (options.excludeCredentials ?? []) as Array<
    Record<string, unknown>
  >;
  return {
    ...options,
    challenge: decodeBase64Url(String(options.challenge)),
    user: {
      ...user,
      id: decodeBase64Url(String(user.id)),
    },
    excludeCredentials: excludeCredentials.map((credential) => ({
      ...credential,
      id: decodeBase64Url(String(credential.id)),
    })),
  } as PublicKeyCredentialCreationOptions;
}

function authenticationOptionsForBrowser(
  options: Record<string, unknown>,
): PublicKeyCredentialRequestOptions {
  const allowCredentials = (options.allowCredentials ?? []) as Array<
    Record<string, unknown>
  >;
  return {
    ...options,
    challenge: decodeBase64Url(String(options.challenge)),
    allowCredentials: allowCredentials.map((credential) => ({
      ...credential,
      id: decodeBase64Url(String(credential.id)),
    })),
  } as PublicKeyCredentialRequestOptions;
}

export async function signInWithPasskey(): Promise<void> {
  if (!supportsPasskeys()) {
    throw new Error("This browser does not support device passkeys.");
  }
  const { data: options } = await api.post<Record<string, unknown>>(
    "/auth/passkey/authentication/options",
  );
  const credential = await navigator.credentials.get({
    publicKey: authenticationOptionsForBrowser(options),
  });
  if (!credential) throw new Error("The device passkey prompt was cancelled.");
  await api.post("/auth/passkey/authentication/verify", serializeCredential(credential));
}

export async function registerPasskey(): Promise<void> {
  if (!supportsPasskeys()) {
    throw new Error("This browser does not support device passkeys.");
  }
  const { data: options } = await api.post<Record<string, unknown>>(
    "/auth/passkey/registration/options",
  );
  const credential = await navigator.credentials.create({
    publicKey: registrationOptionsForBrowser(options),
  });
  if (!credential) throw new Error("The device passkey prompt was cancelled.");
  await api.post("/auth/passkey/registration/verify", serializeCredential(credential));
}

export async function signOutPasskey(): Promise<void> {
  await api.post("/auth/passkey/logout");
}

export function usePasskeySession() {
  const [session, setSession] = useState<PasskeySession>({
    authenticated: false,
  });
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<PasskeySession>("/auth/passkey/session");
      setSession(data);
    } catch {
      setSession({ authenticated: false });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { ...session, loading, refresh };
}

export async function listPasskeys(): Promise<PasskeyCredentialSummary[]> {
  const { data } = await api.get<{ credentials: PasskeyCredentialSummary[] }>(
    "/auth/passkey/credentials",
  );
  return data.credentials;
}

export async function deletePasskey(id: string): Promise<void> {
  await api.delete(`/auth/passkey/credentials/${encodeURIComponent(id)}`);
}
