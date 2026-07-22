import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev servers: Vite on :5173, FastAPI on :8000. The proxy below forwards every /api request
// to FastAPI, so the frontend ALWAYS calls relative "/api/..." — no CORS config anywhere
// (in prod FastAPI serves the built app from the same origin instead).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
