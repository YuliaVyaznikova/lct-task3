import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env }
  // Куда дев-сервер проксирует /api: по умолчанию сервис в Docker на 8000.
  const target = env.VITE_API_TARGET || 'http://127.0.0.1:8000'
  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_PORT || 5173),
      proxy: { '/api': { target, changeOrigin: true } },
    },
    build: { outDir: 'dist', emptyOutDir: true },
  }
})
