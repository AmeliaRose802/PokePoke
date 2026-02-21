import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Allow pywebview to connect from any origin
    cors: true,
    // Needed so pywebview can reach the dev server
    host: 'localhost',
    port: 5173,
    strictPort: true,
  },
})
