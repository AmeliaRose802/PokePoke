import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Desktop app bundled with pywebview — large chunks are fine
    chunkSizeWarningLimit: 1000,
  },
  server: {
    // Allow pywebview to connect from any origin
    cors: true,
    // Needed so pywebview can reach the dev server
    host: 'localhost',
    port: 5173,
    strictPort: true,
  },
})
