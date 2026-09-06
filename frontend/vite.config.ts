import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built app is served by FastAPI from frontend/dist at the same origin as
// /api/*, so the production API base is "" (same origin) and no CORS header
// exists to be misconfigured.  The dev proxy below is what lets `npm run dev`
// on :5173 talk to the backend on :8000 without touching CORS at all.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://10.79.57.227:8000",
        changeOrigin: false,
      },
    },
  },
});
