/**
 * Typed client for the EarthTrend API.
 *
 * Types come from `schema.d.ts`, which is generated from `contract/openapi.json`
 * (`npm run api:gen`). Never edit `schema.d.ts` by hand: when the backend changes a
 * route or a schema, regenerating it makes `npm run typecheck` point at every call
 * site that no longer matches.
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type { components, paths };

/** A response or request body by its OpenAPI schema name, e.g. `Schema<"CaseResponse">`. */
export type Schema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export const api = createClient<paths>({
  baseUrl: import.meta.env?.VITE_API_URL ?? "",
  credentials: "include",
});
