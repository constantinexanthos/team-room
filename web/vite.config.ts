import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // During dev, proxy API calls to the team-room server.py on 8765.
      '/projects': 'http://localhost:8765',
      '/recents': 'http://localhost:8765',
      '/topic': 'http://localhost:8765',
      '/topics': 'http://localhost:8765',
      '/topics.json': 'http://localhost:8765',
      '/status': 'http://localhost:8765',
      '/prompt': 'http://localhost:8765',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
