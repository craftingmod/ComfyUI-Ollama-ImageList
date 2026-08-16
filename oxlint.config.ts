import { defineConfig } from "oxlint"

export default defineConfig({
  categories: {
    correctness: "warn",
  },
  ignorePatterns: [".agents/**"],
  plugins: ["import"],
  // https://oxc.rs/docs/guide/usage/linter/rules.html
  rules: {
    "eslint/no-unused-expressions": [
      "warn",
      {
        allowTaggedTemplates: true,
      },
    ],
    "import/extensions": [
      "error",
      "always",
      {
        ignorePackages: true,
        checkTypeImports: true,
      },
    ],
  },
})
