import { afterEach, describe, expect, it } from "bun:test"
import fs from "node:fs/promises"
import os from "node:os"
import Path from "node:path"

import { incrementPatchVersion } from "../../scripts/bump-version.ts"
import {
  initializeTemplate,
  validateGitHubRepo,
  validateGitHubUsername,
  validateProjectId,
  validateProjectName,
  validatePublisherId,
} from "../../scripts/init-template.ts"

const temporaryDirectories: string[] = []

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => fs.rm(directory, { recursive: true, force: true })),
  )
})

describe("template maintenance scripts", () => {
  it("increments only the project patch version", () => {
    const source = `[project]\nname = "example"\nversion = "0.6.1"\n\n[tool.example]\nversion = "9.9.9"\n`
    const result = incrementPatchVersion(source)

    expect(result.currentVersion).toBe("0.6.1")
    expect(result.newVersion).toBe("0.6.2")
    expect(result.updatedToml).toContain('version = "0.6.2"')
    expect(result.updatedToml).toContain('version = "9.9.9"')
  })

  it("validates template identity fields", () => {
    expect(validateProjectId("image-tools")).toBe("image-tools")
    expect(validateProjectName(" Image Tools ")).toBe("Image Tools")
    expect(validateGitHubUsername("octocat")).toBe("octocat")
    expect(validateGitHubRepo("comfyui-image-tools")).toBe("comfyui-image-tools")
    expect(validatePublisherId("octocat.tools")).toBe("octocat.tools")
    expect(() => validateProjectId("Image Tools")).toThrow("Project ID")
  })

  it("initializes this repository layout without the template example node", async () => {
    const targetDir = await fs.mkdtemp(Path.join(os.tmpdir(), "ollama-template-test-"))
    temporaryDirectories.push(targetDir)
    await fs.mkdir(Path.join(targetDir, "frontend", "src"), { recursive: true })
    await fs.mkdir(Path.join(targetDir, "backend"), { recursive: true })
    await Promise.all([
      fs.writeFile(
        Path.join(targetDir, "pyproject.toml"),
        `[project]\nname = "old-id"\nversion = "1.0.0"\n\n[project.urls]\nRepository = "https://github.com/old/repo"\n\n[tool.comfy]\nPublisherId = "old"\nDisplayName = "Old Name"\nIcon = "https://example.com/icon.svg"\n`,
      ),
      fs.writeFile(Path.join(targetDir, "package.json"), '{"name":"old-id","private":true}\n'),
      fs.writeFile(
        Path.join(targetDir, "frontend", "src", "constants.ts"),
        'export const PROJECT_ID = "old-id"\nexport const PROJECT_NAME = "Old Name"\n',
      ),
      fs.writeFile(
        Path.join(targetDir, "backend", "__init__.py"),
        'PROJECT_ID = "old-id"\nPROJECT_NAME = "Old Name"\n',
      ),
    ])

    await initializeTemplate(
      "image-tools",
      "Image Tools",
      "octocat",
      "comfyui-image-tools",
      "octocat",
      targetDir,
    )

    const [pyproject, packageJson, constants, backend] = await Promise.all([
      fs.readFile(Path.join(targetDir, "pyproject.toml"), "utf8"),
      fs.readFile(Path.join(targetDir, "package.json"), "utf8"),
      fs.readFile(Path.join(targetDir, "frontend", "src", "constants.ts"), "utf8"),
      fs.readFile(Path.join(targetDir, "backend", "__init__.py"), "utf8"),
    ])
    expect(pyproject).toContain('name = "image-tools"')
    expect(pyproject).toContain('PublisherId = "octocat"')
    expect(JSON.parse(packageJson).name).toBe("image-tools")
    expect(constants).toContain('PROJECT_NAME = "Image Tools"')
    expect(backend).toContain('PROJECT_ID = "image-tools"')
  })
})
