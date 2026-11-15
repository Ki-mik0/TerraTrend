import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev proxy target; set API_PROXY_TARGET when the API runs on another port.
const api = process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': api,
      '/health': api,
    },
  },
})
