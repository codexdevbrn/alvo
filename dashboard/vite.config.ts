import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxy = {
  '/api': {
    // 8004: esta é a árvore de empacotamento (branch feat/empacotamento-exe).
    // A instalação oficial roda na 8003 — apontar para ela daqui faria o dev
    // desta cópia mexer nos dados de produção.
    target: 'http://127.0.0.1:8004',
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
