import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 백엔드(8100)로 프록시 — 프론트 코드에서는 /api/... 상대경로만 쓰면 된다(CORS 불필요)
    proxy: {
      '/api': { target: 'http://127.0.0.1:8100', changeOrigin: true },
    },
  },
})
