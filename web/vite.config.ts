import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev proxy target; set API_PROXY_TARGET when the API runs on another port.
const api = process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // maplibre-gl's worker is an ES module (see src/maplibreWorker.ts).
  worker: { format: 'es' },
  // Pre-bundle both together so react-map-gl and src/maplibreWorker.ts share one maplibre instance.
  optimizeDeps: { include: ['maplibre-gl', 'react-map-gl/maplibre'] },
  server: {
    proxy: {
      '/api': api,
      '/health': api,
    },
  },
})
