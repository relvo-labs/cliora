import { existsSync, readdirSync, readFileSync } from "node:fs";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, loadEnv, type Plugin } from "vite";
import vue from "@vitejs/plugin-vue";

// PDF.js's static assets, self-hosted under /pdfjs/ (ADR 0029 §12, plan/31/05
// BP-07 §2). Written here rather than taken from a copy plugin, so the preview
// adds exactly one dependency (pdfjs-dist) to review.
//
// Four directories, and one exclusion that matters: wasm/ also ships
// `quickjs-eval.*`, the JavaScript engine of PDF.js's scripting sandbox. It is
// only ever loaded by `pdf.sandbox.mjs`, which is never imported, and it is not
// copied either — a document's JavaScript has no engine to run on.
const PDFJS_ROOT = fileURLToPath(
  new URL("./node_modules/pdfjs-dist/", import.meta.url),
);
const PDFJS_DIRS = ["cmaps", "standard_fonts", "wasm", "iccs"];
const PDFJS_EXCLUDED = /^quickjs-eval\./;
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const PDFJS_TYPES: Record<string, string> = {
  ".wasm": "application/wasm",
  ".js": "text/javascript",
  ".ttf": "font/ttf",
};

export function pdfjsAssetAllowed(dir: string, name: string): boolean {
  return (
    PDFJS_DIRS.includes(dir) &&
    SAFE_NAME.test(name) &&
    !PDFJS_EXCLUDED.test(name)
  );
}

function pdfjsAssets(): Plugin {
  return {
    name: "cliora-pdfjs-assets",
    configureServer(server) {
      server.middlewares.use("/pdfjs/", (req, res, next) => {
        const [dir, name, ...rest] = (req.url ?? "")
          .split("?")[0]
          .split("/")
          .filter(Boolean);
        const file = dir && name ? join(PDFJS_ROOT, dir, name) : "";
        if (rest.length || !pdfjsAssetAllowed(dir, name) || !existsSync(file)) {
          next();
          return;
        }
        res.setHeader(
          "Content-Type",
          PDFJS_TYPES[extname(name)] ?? "application/octet-stream",
        );
        res.end(readFileSync(file));
      });
    },
    generateBundle() {
      for (const dir of PDFJS_DIRS) {
        for (const name of readdirSync(join(PDFJS_ROOT, dir))) {
          if (!pdfjsAssetAllowed(dir, name)) continue;
          this.emitFile({
            type: "asset",
            fileName: `pdfjs/${dir}/${name}`,
            source: readFileSync(join(PDFJS_ROOT, dir, name)),
          });
        }
      }
    },
  };
}

// The product name has one source (VITE_PRODUCT_NAME, default "Cliora") and two
// consumers: AppLayout's brand and the document title. index.html cannot read an env
// var at runtime, so the placeholder is substituted here at build time — which is
// also what stops the browser tab from naming something the page contradicts.
const DEFAULT_PRODUCT_NAME = "Cliora";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const productName = env.VITE_PRODUCT_NAME || DEFAULT_PRODUCT_NAME;
  // Where the dev server proxies /api and /ws. Read from `process.env`, with no
  // `VITE_` prefix, and that is the point: a `VITE_`-prefixed variable is
  // inlined into the client bundle, and this value must never reach the
  // browser.
  //
  // `VITE_API_BASE_URL` is a different thing and must not be reused here — it
  // is the API client's own base URL (`src/api/client.ts`), so setting it makes
  // the *browser* fetch that absolute address. Through a tunnel that means the
  // browser calling 127.0.0.1 on the viewer's own machine: connection refused,
  // plus a CORS preflight because it is suddenly cross-origin. Empty is the
  // right value for it in dev — relative URLs are same-origin and land here.
  //
  //   CLIORA_DEV_PROXY_TARGET=http://127.0.0.1:8100 npm run dev
  const apiTarget =
    process.env.CLIORA_DEV_PROXY_TARGET || "http://127.0.0.1:8000";
  // Extra Host headers the dev server will answer to, comma-separated. Needed
  // when the dev server is reached through a tunnel (pinggy, ngrok, a
  // Codespaces forward): Vite answers only to localhost by default, and a
  // tunnelled request arrives with the tunnel's hostname.
  //
  // Not hard-coded, and the default is deliberately left alone. Vite's host
  // check is what stops a page on another origin from driving this server
  // through DNS rebinding — the dev server can read any file the project can,
  // so widening it for everyone to suit one person's tunnel is the wrong
  // trade. A leading dot covers subdomains, so `.pinggy.link` survives the
  // tunnel handing out a new random subdomain on every restart:
  //
  //   VITE_ALLOWED_HOSTS=.pinggy.link npm run dev
  //
  // `true` allows any host; use it only on a machine with nothing else on it.
  const allowedHostsEnv = env.VITE_ALLOWED_HOSTS?.trim();
  const allowedHosts =
    allowedHostsEnv === "true"
      ? true
      : allowedHostsEnv
        ? allowedHostsEnv
            .split(",")
            .map((host) => host.trim())
            .filter(Boolean)
        : undefined;
  return {
    plugins: [
      vue(),
      pdfjsAssets(),
      {
        name: "cliora-product-name",
        transformIndexHtml: (html) =>
          html.replaceAll("%VITE_PRODUCT_NAME%", productName),
      },
    ],
    server: {
      host: "0.0.0.0",
      // `undefined` leaves Vite's own default in place rather than replacing it
      // with an empty list, which would answer to nothing at all.
      ...(allowedHosts === undefined ? {} : { allowedHosts }),
      // Same-origin API/WS in dev: the typed client uses relative URLs, so
      // proxy them to the local Central. Override the target with
      // CLIORA_DEV_PROXY_TARGET (see above for why not VITE_API_BASE_URL).
      proxy: {
        "/api": { target: apiTarget, changeOrigin: true },
        "/ws": {
          target: apiTarget.replace(/^http/, "ws"),
          ws: true,
          changeOrigin: true,
        },
      },
    },
  };
});
