import { defineConfig } from "oxfmt"

export default defineConfig({
  ignorePatterns: [
    ".agents/**",
    ".vscode/**",
    "**/*.md",
    "presets/**",
    "workflows/**",
    "subgraphs/**",
    "package.json",
  ],
  tabWidth: 2,
  semi: false,
  singleQuote: false,
  sortImports: true,
  sortTailwindcss: true,
  sortPackageJson: true,
})
