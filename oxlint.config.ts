import { defineConfig } from "oxlint"
export default defineConfig({
  categories: {
    correctness: "warn",
  },
  options: {
    typeAware: true,
    typeCheck: true,
  },
  ignorePatterns: [".agents/**", "docs/**", "presets/**", "subgraphs/**"],
  plugins: ["import", "typescript", "oxc"],
  jsPlugins: [],
  // https://oxc.rs/docs/guide/usage/linter/rules.html
  rules: {
    "eslint/no-unused-expressions": [
      "warn",
      {
        allowTaggedTemplates: true,
      },
    ],
    "import/consistent-type-specifier-style": ["warn", "prefer-top-level-if-only-type-imports"],
    "import/extensions": [
      "error",
      "always",
      {
        ignorePackages: true,
        checkTypeImports: true,
      },
    ],
    "import/no-commonjs": "error",
    "import/no-duplicates": "warn",
    "import/no-cycle": [
      "error",
      {
        maxDepth: 3,
      },
    ],
    /* Too much effort on react */
    "typescript/unbound-method": "off",
  },
})
