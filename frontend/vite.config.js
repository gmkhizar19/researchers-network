import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Port 5173 is the origin allowed by CORS_ORIGINS in the backend .env.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
});
