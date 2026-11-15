/** Absolute URL for calls made outside the typed client (SSE streams, file downloads). */
export function apiUrl(path: string): string {
  const base = (import.meta.env?.VITE_API_URL ?? "").replace(/\/$/, "");
  return `${base}${path}`;
}
