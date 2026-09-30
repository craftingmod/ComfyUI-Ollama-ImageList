import fs from "node:fs/promises"
import Path from "node:path"

import { $ } from "bun"

export async function getProjectVersion(projectDir: string): Promise<string> {
  const version = (await $`uvx uv-dynamic-versioning`.cwd(projectDir).text()).trim()
  if (!version) throw new Error("uv-dynamic-versioning returned an empty project version.")
  return version
}

export function registryVersionSource(version: string): string {
  if (!/^\d+\.\d+\.\d+$/.test(version)) {
    throw new Error(`Registry publishing requires a stable X.Y.Z version, got ${version}.`)
  }
  return `__version__ = "${version}"\n`
}

if (import.meta.main) {
  const projectDir = Path.resolve(import.meta.dir, "../")
  const version = await getProjectVersion(projectDir)
  await fs.writeFile(
    Path.join(projectDir, "backend", "_version.py"),
    registryVersionSource(version),
  )
  console.log(`Generated backend/_version.py for Registry version ${version}.`)
}
