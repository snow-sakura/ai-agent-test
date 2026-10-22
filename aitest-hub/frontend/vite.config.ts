import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import process from 'node:process'

// 后端地址可经 VITE_API_TARGET 覆盖（默认 8000；本地多实例并行时用 8010 等）
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

// Frontend/backend separation: dev proxy -> FastAPI, prod build served separately.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
      // 缺陷附件等上传资源以 /uploads 相对路径回显；prod 由 FastAPI 同源挂载，
      // dev 需转发到后端，否则命中 vite SPA fallback 返回 HTML（裂图/下载错文件）
      '/uploads': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
})
