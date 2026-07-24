import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxy = {
  '/api': {
    target: 'http://127.0.0.1:8003',
    changeOrigin: true,
    // Summaries grandes (dezenas de MB); não cortar no meio.
    timeout: 600_000,
    proxyTimeout: 600_000,
  },
} as const

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: { ...apiProxy },
  },
  // Preview (build) é bem mais rápido na LAN do que `vite --host` em dev.
  preview: {
    host: true,
    port: 5173,
    proxy: { ...apiProxy },
  },
})
