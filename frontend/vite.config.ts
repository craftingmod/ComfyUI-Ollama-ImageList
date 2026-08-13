import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, type Plugin } from "vite";

export const FRONTEND_ROOT = fileURLToPath(new URL(".", import.meta.url));
export const FRONTEND_ENTRY = path.resolve(FRONTEND_ROOT, "src/index.ts");
export const WEB_OUTPUT_DIRECTORY = path.resolve(FRONTEND_ROOT, "../web");
export const COMFY_PUBLIC_IMPORTS = ["/scripts/app.js", "/scripts/api.js"] as const;

export function enforceSingleJavaScriptBundle(): Plugin {
  return {
    name: "enforce-single-comfy-extension-bundle",
    generateBundle(_options, bundle) {
      const javaScriptFiles = Object.keys(bundle).filter((name) => name.endsWith(".js"));
      if (javaScriptFiles.length !== 1 || javaScriptFiles[0] !== "index.js") {
        this.error(
          `ComfyUI must receive exactly web/index.js; emitted: ${javaScriptFiles.join(", ") || "none"}.`,
        );
      }
    },
  };
}

export default defineConfig({
  root: FRONTEND_ROOT,
  publicDir: false,
  plugins: [enforceSingleJavaScriptBundle()],
  build: {
    outDir: WEB_OUTPUT_DIRECTORY,
    emptyOutDir: true,
    copyPublicDir: false,
    target: "es2020",
    sourcemap: false,
    cssCodeSplit: false,
    modulePreload: false,
    rolldownOptions: {
      input: FRONTEND_ENTRY,
      external: [...COMFY_PUBLIC_IMPORTS],
      output: {
        format: "es",
        entryFileNames: "index.js",
        codeSplitting: false,
        assetFileNames: "[name][extname]",
      },
    },
  },
});
