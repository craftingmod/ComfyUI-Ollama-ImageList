import { $ } from "bun"

export async function getProjectVersion(projectDir: string): Promise<string> {
  const version = (await $`uvx uv-dynamic-versioning`.cwd(projectDir).text()).trim()
  if (!version) throw new Error("uv-dynamic-versioning returned an empty project version.")
  return version
}
