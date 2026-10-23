import { defineConfig } from 'vite'
import solid from 'vite-plugin-solid'

export default defineConfig({
  plugins: [solid()],
  server: {
    // 開発時は uvicorn（:8000）へAPIを転送する。本番は FastAPI が同一オリジンで配信する
    proxy: { '/api': 'http://localhost:8000' },
  },
})
