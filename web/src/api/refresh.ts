/**
 * Keeps the session alive. A session token lives an hour; before it runs out (or right after a 401)
 * it is swapped for a new one through `POST /api/v1/session/refresh`. Plain fetch is used here so
 * the typed client can call this from its own middleware without a loop.
 */
import { useStore } from "../store/useStore";
import { apiUrl } from "./url";

/** Seconds before expiry at which the token is renewed ahead of time. */
export const REFRESH_AHEAD = 120;

/** Unix seconds when a JWT stops working, read from its payload; null if it has no expiry. */
export function tokenExpiry(token: string | null): number | null {
  if (!token) return null;
  try {
    const part = token.split(".")[1] ?? "";
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "="));
    const exp = (JSON.parse(json) as { exp?: unknown }).exp;
    return typeof exp === "number" ? exp : null;
  } catch {
    return null;
  }
}

/** True when the token is gone, has no expiry, or expires within `ahead` seconds. */
export function needsRefresh(token: string | null, ahead = REFRESH_AHEAD): boolean {
  const exp = tokenExpiry(token);
  return exp === null || exp - Date.now() / 1000 <= ahead;
}

let pending: Promise<string | null> | null = null;

/**
 * Swap the current token for a fresh one. Concurrent callers share one request.
 * Resolves with the new token, or null when the server refused it (the session is then cleared and
 * SessionSync opens a guest session). A network failure rejects and keeps the current session.
 */
export function refreshSession(): Promise<string | null> {
  if (pending) return pending;
  const token = useStore.getState().token;
  if (!token) return Promise.resolve(null);
  pending = (async () => {
    const response = await fetch(apiUrl("/api/v1/session/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (response.status === 401 || response.status === 422) {
      // Only drop the session if nobody replaced it meanwhile (a sign-in in another tab, say).
      if (useStore.getState().token === token) useStore.getState().clearSession();
      return null;
    }
    if (!response.ok) throw new Error(`Session refresh failed (${response.status})`);
    const { token: fresh } = (await response.json()) as { token: string };
    const state = useStore.getState();
    if (state.token === token) state.setSession({ token: fresh, userId: state.userId ?? "", role: state.role ?? "" });
    return fresh;
  })().finally(() => {
    pending = null;
  });
  return pending;
}

/** A fetch with the bearer token that renews the session once and retries if the server answers 401. */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const send = (token: string | null) => {
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(apiUrl(path), { ...init, headers });
  };
  if (needsRefresh(useStore.getState().token, 0)) await refreshSession().catch(() => null);
  const response = await send(useStore.getState().token);
  if (response.status !== 401) return response;
  const fresh = await refreshSession().catch(() => null);
  return fresh ? send(fresh) : response;
}
