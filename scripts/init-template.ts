import fs from "node:fs/promises"
import Path from "node:path"
import { createInterface } from "node:readline/promises"

const projectDir = Path.resolve(import.meta.dir, "../")

function requireMatch(value: string, pattern: RegExp, message: string): string {
  const trimmed = value.trim()
  if (!pattern.test(trimmed)) throw new Error(message)
  return trimmed
}

export function validateProjectId(value: string): string {
  const projectId = requireMatch(
    value,
    /^[a-z](?:[a-z0-9]|[._-](?=[a-z0-9]))*$/,
    "Project ID must start with a lowercase letter and use lowercase letters, numbers, '.', '_' or single '-'.",
  )
  if (projectId.length >= 100) throw new Error("Project ID must be less than 100 characters long.")
  return projectId
}

export function validateProjectName(value: string): string {
  const projectName = value.trim()
  const hasControlCharacter = [...projectName].some((character) => {
    const codePoint = character.codePointAt(0)!
    return codePoint < 32 || codePoint === 127
  })
  if (projectName.length === 0 || projectName.length > 100 || hasControlCharacter) {
    throw new Error(
      "Project Name must be a non-empty display name without control characters and at most 100 characters long.",
    )
  }
  return projectName
}

export function validateGitHubUsername(value: string): string {
  const username = requireMatch(
    value,
    /^(?!.*--)[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/,
    "GitHub username must contain only letters, numbers or single hyphens, and cannot start or end with a hyphen.",
  )
  if (username.length > 39) throw new Error("GitHub username must be at most 39 characters long.")
  return username
}

export function validateGitHubRepo(value: string): string {
  const repo = requireMatch(
    value,
    /^[A-Za-z0-9._-]+$/,
    "GitHub repository name must contain only letters, numbers, '.', '_' or '-'.",
  )
  if (repo.length > 100 || repo === "." || repo === "..") {
    throw new Error("GitHub repository name must be valid and at most 100 characters long.")
  }
  return repo
}

export function validatePublisherId(value: string): string {
  const publisherId = requireMatch(
    value,
    /^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$/,
    "Registry Publisher ID must use lowercase letters, numbers, '.', '_' or '-'.",
  )
  if (publisherId.length > 100) {
    throw new Error("Registry Publisher ID must be at most 100 characters long.")
  }
  return publisherId
}

function replaceQuotedValue(source: string, pattern: RegExp, value: string, label: string): string {
  if (!pattern.test(source)) throw new Error(`Could not find ${label}`)
  return source.replace(pattern, (_match, prefix: string) => `${prefix}${JSON.stringify(value)}`)
}

export async function initializeTemplate(
  projectId: string,
  projectName: string,
  githubUsername: string,
  githubRepo: string,
  publisherId: string,
  targetDir = projectDir,
): Promise<void> {
  const pyprojectPath = Path.join(targetDir, "pyproject.toml")
  const packagePath = Path.join(targetDir, "package.json")
  const constantsPath = Path.join(targetDir, "frontend", "src", "constants.ts")
  const backendPath = Path.join(targetDir, "backend", "__init__.py")
  const [originalPyproject, originalPackage, originalConstants, originalBackend] =
    await Promise.all([
      fs.readFile(pyprojectPath, "utf8"),
      fs.readFile(packagePath, "utf8"),
      fs.readFile(constantsPath, "utf8"),
      fs.readFile(backendPath, "utf8"),
    ])

  const projectSectionPattern = /(^\[project\]\s*$)([\s\S]*?)(?=^\[|(?![\s\S]))/m
  const projectSection = originalPyproject.match(projectSectionPattern)
  if (!projectSection) throw new Error("Could not find [project] in pyproject.toml")

  const updatedProjectSection = replaceQuotedValue(
    projectSection[0],
    /^(name\s*=\s*)["'][^"']+["']\s*$/m,
    projectId,
    "project.name in pyproject.toml",
  )
  let updatedPyproject = originalPyproject.replace(
    projectSectionPattern,
    () => updatedProjectSection,
  )
  updatedPyproject = replaceQuotedValue(
    updatedPyproject,
    /^(Repository\s*=\s*)["'][^"']+["']\s*$/m,
    `https://github.com/${githubUsername}/${githubRepo}`,
    "project.urls.Repository in pyproject.toml",
  )
  updatedPyproject = replaceQuotedValue(
    updatedPyproject,
    /^(PublisherId\s*=\s*)["'][^"']+["']\s*$/m,
    publisherId,
    "tool.comfy.PublisherId in pyproject.toml",
  )
  updatedPyproject = replaceQuotedValue(
    updatedPyproject,
    /^(DisplayName\s*=\s*)["'][^"']+["']\s*$/m,
    projectName,
    "tool.comfy.DisplayName in pyproject.toml",
  )
  updatedPyproject = replaceQuotedValue(
    updatedPyproject,
    /^(Icon\s*=\s*)["'][^"']+["']\s*$/m,
    `https://cdn.jsdelivr.net/gh/${githubUsername}/${githubRepo}/assets/icon.svg`,
    "tool.comfy.Icon in pyproject.toml",
  )

  const packageJson = JSON.parse(originalPackage) as Record<string, unknown>
  packageJson.name = projectId
  const updatedPackage = `${JSON.stringify(packageJson, null, 2)}\n`
  let updatedConstants = replaceQuotedValue(
    originalConstants,
    /^(export const PROJECT_ID\s*=\s*)["'][^"']+["']\s*$/m,
    projectId,
    "PROJECT_ID in frontend/src/constants.ts",
  )
  updatedConstants = replaceQuotedValue(
    updatedConstants,
    /^(export const PROJECT_NAME\s*=\s*)["'][^"']+["']\s*$/m,
    projectName,
    "PROJECT_NAME in frontend/src/constants.ts",
  )
  let updatedBackend = replaceQuotedValue(
    originalBackend,
    /^(PROJECT_ID\s*=\s*)["'][^"']+["']\s*$/m,
    projectId,
    "PROJECT_ID in backend/__init__.py",
  )
  updatedBackend = replaceQuotedValue(
    updatedBackend,
    /^(PROJECT_NAME\s*=\s*)["'][^"']+["']\s*$/m,
    projectName,
    "PROJECT_NAME in backend/__init__.py",
  )

  await Promise.all([
    fs.writeFile(pyprojectPath, updatedPyproject),
    fs.writeFile(packagePath, updatedPackage),
    fs.writeFile(constantsPath, updatedConstants),
    fs.writeFile(backendPath, updatedBackend),
  ])
}

async function main(): Promise<void> {
  let answers: [string, string, string, string, string]
  if (process.stdin.isTTY) {
    const input = createInterface({ input: process.stdin, output: process.stdout })
    try {
      answers = [
        await input.question("Project ID: "),
        await input.question("Project Name: "),
        await input.question("GitHub username: "),
        await input.question("GitHub repository name: "),
        await input.question("Comfy Registry Publisher ID: "),
      ]
    } finally {
      input.close()
    }
  } else {
    const lines = (await Bun.stdin.text()).split(/\r?\n/)
    if (lines.length < 5) {
      throw new Error(
        "Expected five stdin lines: Project ID, Project Name, GitHub username, GitHub repository name and Comfy Registry Publisher ID.",
      )
    }
    answers = [lines[0]!, lines[1]!, lines[2]!, lines[3]!, lines[4]!]
  }

  await initializeTemplate(
    validateProjectId(answers[0]),
    validateProjectName(answers[1]),
    validateGitHubUsername(answers[2]),
    validateGitHubRepo(answers[3]),
    validatePublisherId(answers[4]),
  )
  console.log(
    `Initialized ${answers[1]!.trim()} (${answers[0]!.trim()}) for https://github.com/${answers[2]!.trim()}/${answers[3]!.trim()}.`,
  )
  console.log("Run `uv lock` and `bun install` to refresh the lockfiles.")
}

if (import.meta.main) {
  await main()
}
