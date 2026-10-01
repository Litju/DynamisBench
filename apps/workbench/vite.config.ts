import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// DEV-URL must match `build.devUrl` in apps/desktop/src-tauri/tauri.conf.json:
// the Tauri shell loads the workbench from this server in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
