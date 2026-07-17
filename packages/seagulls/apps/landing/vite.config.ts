import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Production serves the landing page from the shared web bucket under the
// `landing/` prefix, so built asset URLs need that base. Dev keeps `/` so
// `public/config.js` is reachable at /config.js like the deployed runtime
// config.
export default defineConfig(({ command, isPreview }) => ({
  base: command === "build" || isPreview ? "/landing/" : "/",
  plugins: [react()],
  test: {
    environment: "jsdom",
  },
}));
