import fs from "node:fs/promises"
import Path from "node:path"

import { $ } from "bun"

type ProjectConfig = {
  project?: { name?: unknown; version?: unknown }
}

export type GitHubReleaseInfo = {
  archivePath: string
  projectName: string
  version: string
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`Expected ${field} to be a non-empty string in pyproject.toml`)
  }
  return value.trim()
}

export function githubReleaseInfo(
  pyprojectSource: string,
  githubRefName: string,
): GitHubReleaseInfo {
  const pyproject = Bun.TOML.parse(pyprojectSource) as ProjectConfig
  const projectName = requireString(pyproject.project?.name, "project.name")
  const version = requireString(pyproject.project?.version, "project.version")
  const expectedTag = `v${version}`

  if (githubRefName !== expectedTag) {
    throw new Error(`Tag ${githubRefName} does not match project version ${expectedTag}.`)
  }

  return {
    archivePath: `build/${projectName}-${version}.zip`,
    projectName,
    version,
  }
}

export async function prepareGitHubRelease(
  projectRoot = Path.resolve(import.meta.dir, "../"),
  githubRefName = process.env.GITHUB_REF_NAME ?? "",
  githubOutput = process.env.GITHUB_OUTPUT ?? "",
): Promise<GitHubReleaseInfo> {
  if (!githubRefName) {
    throw new Error("GITHUB_REF_NAME is required to prepare a GitHub Release.")
  }
  if (!githubOutput) {
    throw new Error("GITHUB_OUTPUT is required to publish the archive step output.")
  }

  const pyprojectSource = await fs.readFile(Path.join(projectRoot, "pyproject.toml"), "utf8")
  const release = githubReleaseInfo(pyprojectSource, githubRefName)

  await $`bun run build:custom-node`.cwd(projectRoot)

  const absoluteArchivePath = Path.join(projectRoot, release.archivePath)
  const archiveStats = await fs.stat(absoluteArchivePath).catch(() => undefined)
  if (!archiveStats?.isFile()) {
    throw new Error(`Expected release archive was not created: ${release.archivePath}`)
  }

  await fs.appendFile(githubOutput, `archive=${release.archivePath}\n`, "utf8")
  console.log(`Prepared ${release.archivePath} for GitHub Release ${githubRefName}.`)
  return release
}

if (import.meta.main) {
  await prepareGitHubRelease()
}
