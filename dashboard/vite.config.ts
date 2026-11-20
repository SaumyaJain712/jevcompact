import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on 127.0.0.1:8000 (`jevcompact serve`).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
