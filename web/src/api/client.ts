/**
 * Typed client for the EarthTrend API.
 *
 * Types come from `schema.d.ts`, which is generated from `contract/openapi.json`
 * (`npm run api:gen`). Never edit `schema.d.ts` by hand.
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";
import { useStore } from "../store/useStore";
import { needsRefresh, refreshSession } from "./refresh";

export type { components, paths };

/** A response or request body by its OpenAPI schema name, e.g. `Schema<"CaseResponse">`. */
export type Schema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export const api = createClient<paths>({
  baseUrl: import.meta.env?.VITE_API_URL ?? "",
});

/** Copies of sent requests, so one rejected for an expired session can be sent again. */
const sent = new Map<string, Request>();

api.use({
  async onRequest({ request, id }) {
    // Renew a token that is about to run out before it is used; sign-in calls carry their own credentials.
    if (!isSessionCall(request) && needsRefresh(useStore.getState().token, 30)) await refreshSession().catch(() => null);
    const token = useStore.getState().token;
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    if (!isSessionCall(request)) sent.set(id, request.clone());
    return request;
  },
  async onResponse({ response, id }) {
    const original = sent.get(id);
    sent.delete(id);
    if (response.status !== 401 || !original) return response;
    const fresh = await refreshSession().catch(() => null);
    if (!fresh) return response;
    const retry = new Request(original, { headers: new Headers(original.headers) });
    retry.headers.set("Authorization", `Bearer ${fresh}`);
    return fetch(retry);
  },
  onError({ id }) {
    sent.delete(id);
  },
});

/** Sign-in, guest and refresh calls: never retried, never renewed first. */
function isSessionCall(request: Request): boolean {
  return request.method === "POST" && new URL(request.url, window.location.origin).pathname.startsWith("/api/v1/session");
}
