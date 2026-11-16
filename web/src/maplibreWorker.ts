/**
 * maplibre-gl 6 looks for its worker next to its own module. Vite moves that module into its
 * dependency cache (dev) or a hashed chunk (build), so the worker is never found. Let Vite bundle
 * the worker itself and hand maplibre the URL of the result.
 */
import { setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

setWorkerUrl(workerUrl);
