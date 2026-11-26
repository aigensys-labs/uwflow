import { defineConfig, loadEnv } from 'vite'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'

const frontendDirectory = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, frontendDirectory, '')
  // Docker Compose injects this into the container process environment.
  // Vite's loadEnv() reads .env files, so check process.env explicitly first.
  const apiTarget = process.env.VITE_STUDIO_API_URL || env.VITE_STUDIO_API_URL || 'http://127.0.0.1:9000'

  return {
    plugins: [react()],
    // Docker keeps node_modules in a writable named volume outside the
    // read-only frontend source mount. Use that volume for Vite's optimizer.
    // Local development retains Vite's normal project-relative cache path.
    cacheDir: process.env.UWFLOW_VITE_CACHE_DIR || 'node_modules/.vite',
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
