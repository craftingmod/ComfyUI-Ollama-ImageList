import fs from "node:fs/promises"
import Path from "node:path"

import { $ } from "bun"

const projectDir = Path.resolve(import.meta.dir, "../")
const tomlPath = Path.resolve(projectDir, "pyproject.toml")

$.cwd(projectDir)

const statusBeforeBump = (await $`git status --porcelain --untracked-files=normal`.text()).trim()
const wasClean = statusBeforeBump.length === 0

const pyprojectToml = await fs.readFile(tomlPath, { encoding: "utf8" })
const projectSection = /(^\[project\]\s*$)([\s\S]*?)(?=^\[|(?![\s\S]))/m
const projectMatch = pyprojectToml.match(projectSection)

if (!projectMatch) {
  throw new Error("Could not find the [project] section in pyproject.toml")
}

const versionPattern = /^(version\s*=\s*["'])(\d+)\.(\d+)\.(\d+)(["']\s*)$/m
const versionMatch = projectMatch[2]!.match(versionPattern)

if (!versionMatch) {
  throw new Error("Could not find a semantic version in pyproject.toml's [project] section")
}

const currentVersion = `${versionMatch[2]}.${versionMatch[3]}.${versionMatch[4]}`
const newVersion = `${versionMatch[2]}.${versionMatch[3]}.${Number(versionMatch[4]) + 1}`
const updatedProjectSection = projectMatch[0].replace(
  versionPattern,
  (_, prefix: string, _major: string, _minor: string, _patch: string, suffix: string) =>
    `${prefix}${newVersion}${suffix}`,
)
const updatedToml = pyprojectToml.replace(projectSection, () => updatedProjectSection)

const tagName = `v${newVersion}`
if (wasClean) {
  const existingTag = (await $`git tag --list ${tagName}`.text()).trim()

  if (existingTag) {
    throw new Error(`Tag ${tagName} already exists; refusing to bump the version`)
  }
}

await fs.writeFile(tomlPath, updatedToml)
await $`uv sync`

console.log(`Bumped pyproject.toml from ${currentVersion} to ${newVersion}.`)

if (wasClean) {
  await $`git add -- pyproject.toml uv.lock`
  await $`git commit -m ${`bump: version to ${newVersion}.`}`
  await $`git tag ${tagName}`
  console.log(`Created commit and tag ${tagName}.`)
  console.log(`Push tag using commands:\ngit push origin ${tagName}`)
} else {
  console.log("Skipped commit and tag because the working tree was not clean before the bump.")
  console.log("Please manually commit and tagging:")
  console.log(`git tag ${tagName}\ngit push origin ${tagName}`)
}
