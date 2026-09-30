import fs from "node:fs/promises"
import Path from "node:path"

import { $ } from "bun"

export async function getProjectVersion(projectDir: string): Promise<string> {
  const version = (await $`uvx uv-dynamic-versioning`.cwd(projectDir).text()).trim()
  if (!version) throw new Error("uv-dynamic-versioning returned an empty project version.")
  return version
}

export function registryPyproject(source: string, version: string): string {
  if (!/^\d+\.\d+\.\d+$/.test(version)) {
    throw new Error(`Registry publishing requires a stable X.Y.Z version, got ${version}.`)
  }
  const dynamicVersion = /^dynamic[ \t]*=[ \t]*\["version"\][ \t]*\r?$/m
  if (!dynamicVersion.test(source)) {
    throw new Error('Expected dynamic = ["version"] in pyproject.toml.')
  }
  return source.replace(dynamicVersion, `version = "${version}"`)
}

if (import.meta.main) {
  const projectDir = Path.resolve(import.meta.dir, "../")
  const version = await getProjectVersion(projectDir)
  const pyprojectPath = Path.join(projectDir, "pyproject.toml")
  const source = await fs.readFile(pyprojectPath, "utf8")
  await fs.writeFile(pyprojectPath, registryPyproject(source, version))
  console.log(`Prepared Registry metadata for version ${version}.`)
}
