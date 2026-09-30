import { expect, it } from "bun:test"

import { registryPyproject } from "../../scripts/project-version.ts"

it("populates a static Registry version while preserving other project metadata", () => {
  const source =
    '[project]\nname = "test-node"\ndynamic = ["version"]\nrequires-python = ">=3.12"\n'
  expect(Bun.TOML.parse(registryPyproject(source, "1.2.3"))).toEqual({
    project: { name: "test-node", version: "1.2.3", "requires-python": ">=3.12" },
  })
  expect(() => registryPyproject(source, "1.2.3.dev1")).toThrow("stable X.Y.Z")
  expect(() => registryPyproject('[project]\nversion = "1.2.3"\n', "1.2.4")).toThrow(
    'Expected dynamic = ["version"]',
  )
})
