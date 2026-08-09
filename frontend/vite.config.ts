import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

// The product name has one source (VITE_PRODUCT_NAME, default "Cliora") and two
// consumers: AppLayout's brand and the document title. index.html cannot read an env
// var at runtime, so the placeholder is substituted here at build time — which is
// also what stops the browser tab from naming something the page contradicts.
const DEFAULT_PRODUCT_NAME = "Cliora";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const productName = env.VITE_PRODUCT_NAME || DEFAULT_PRODUCT_NAME;
  const allowedHosts = (env.VITE_ALLOWED_HOSTS || "")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean);
  return {
    plugins: [
      vue(),
      {
        name: "cliora-product-name",
        transformIndexHtml: (html) =>
          html.replaceAll("%VITE_PRODUCT_NAME%", productName),
      },
    ],
    server: {
      host: "0.0.0.0",
      // Comma-separated exact hosts for development tunnels. Avoid wildcard tunnel
      // domains: keeping the allowlist explicit preserves Vite's Host protection.
      allowedHosts,
      // Same-origin API/WS in dev: the typed client uses relative URLs, so proxy
      // them to the local Central. Override the backend target with VITE_API_BASE_URL.
      proxy: {
        "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
        "/ws": { target: "ws://127.0.0.1:8000", ws: true, changeOrigin: true },
      },
    },
  };
});
