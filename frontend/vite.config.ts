import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// En desarrollo, Vite (5173) reenvía la API al backend FastAPI (8000):
//   uvicorn api.main:app --app-dir backend --port 8000
// En producción no hay proxy: FastAPI sirve `dist/` desde el mismo origen
// (ver FRONTEND_DIST en backend/api/main.py), así la cookie de sesión y el SSE
// funcionan sin CORS.
const backend = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/docs': { target: backend, changeOrigin: true },
      '/openapi.json': { target: backend, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, target: 'es2022' },
})
