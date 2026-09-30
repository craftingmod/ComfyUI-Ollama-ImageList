import { expect, it } from "bun:test"

import { registryVersionSource } from "../../scripts/project-version.ts"

it("generates the version assignment read by comfy-cli", () => {
  expect(registryVersionSource("1.2.3")).toBe('__version__ = "1.2.3"\n')
  expect(() => registryVersionSource("1.2.3.dev1")).toThrow("stable X.Y.Z")
})
