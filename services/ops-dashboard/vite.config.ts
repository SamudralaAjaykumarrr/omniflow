/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-server proxy only. The production image never runs this — nginx.conf
// (services/ops-dashboard/nginx.conf) does the equivalent proxying against
// Docker Compose service names. Here, targets default to the host ports
// docker-compose.yml already publishes, so `npm run dev` works against a
// `make up` stack running alongside it without extra config.
const GATEWAY_TARGET = process.env.VITE_DEV_GATEWAY_TARGET ?? "http://localhost:8080";
const INVENTORY_TARGET = process.env.VITE_DEV_INVENTORY_TARGET ?? "http://localhost:8002";
const ORCHESTRATOR_TARGET = process.env.VITE_DEV_ORCHESTRATOR_TARGET ?? "http://localhost:8003";
const PROMETHEUS_TARGET = process.env.VITE_DEV_PROMETHEUS_TARGET ?? "http://localhost:9090";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/gw": { target: GATEWAY_TARGET, changeOrigin: true, rewrite: (p) => p.replace(/^\/gw/, "") },
      "/inventory-api": {
        target: INVENTORY_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/inventory-api/, ""),
      },
      "/orchestrator-api": {
        target: ORCHESTRATOR_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/orchestrator-api/, ""),
      },
      "/prom-api": {
        target: PROMETHEUS_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/prom-api/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "text-summary"],
    },
  },
});
