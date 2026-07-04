import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backendTarget = process.env.VITE_BACKEND_URL || 'http://localhost:8000'
const insightTarget = process.env.VITE_INSIGHT_URL || 'http://localhost:8001'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': backendTarget,
      '/logs': backendTarget,
      '/ingest': backendTarget,
      '/search': backendTarget,
      '/health': backendTarget,
      '/metrics': backendTarget,
      '/v1': backendTarget,
      '/explain': insightTarget,
    },
  },
})
