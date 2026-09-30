import { describe, expect, it } from "bun:test"
import fs from "node:fs/promises"
import os from "node:os"
import Path from "node:path"

import { validateRelease, validateReleaseMetadata } from "../../scripts/validate-release.ts"

const metadata = {
  packageName: "ollama-image-list",
  projectName: "ollama-image-list",
  repository: "https://github.com/craftingmod/ComfyUI-llama-multimodal",
  publisherId: "alyac",
  displayName: "Ollama-ImageList",
  icon: "https://cdn.jsdelivr.net/gh/craftingmod/ComfyUI-llama-multimodal/assets/icon.svg",
  frontendProjectId: "ollama-image-list",
  frontendProjectName: "Ollama-ImageList",
  backendProjectId: "ollama-image-list",
  backendProjectName: "Ollama-ImageList",
  githubRepository: "craftingmod/ComfyUI-llama-multimodal",
}

describe("release metadata validation", () => {
  it("reads backend identity without an example node", async () => {
    const projectRoot = await fs.mkdtemp(Path.join(os.tmpdir(), "release-validation-"))
    try {
      await fs.mkdir(Path.join(projectRoot, "frontend", "src"), { recursive: true })
      await fs.mkdir(Path.join(projectRoot, "backend"))
      await fs.writeFile(
        Path.join(projectRoot, "pyproject.toml"),
        `[project]
name = "${metadata.projectName}"
[project.urls]
Repository = "${metadata.repository}"
[tool.comfy]
PublisherId = "${metadata.publisherId}"
DisplayName = "${metadata.displayName}"
Icon = "${metadata.icon}"
`,
      )
      await fs.writeFile(
        Path.join(projectRoot, "package.json"),
        JSON.stringify({ name: metadata.packageName }),
      )
      await fs.writeFile(
        Path.join(projectRoot, "frontend", "src", "constants.ts"),
        `export const PROJECT_ID = "${metadata.frontendProjectId}"\nexport const PROJECT_NAME = "${metadata.frontendProjectName}"\n`,
      )
      await fs.writeFile(
        Path.join(projectRoot, "backend", "__init__.py"),
        `PROJECT_ID = "${metadata.backendProjectId}"\nPROJECT_NAME = "${metadata.backendProjectName}"\n`,
      )
      expect(await validateRelease(projectRoot)).toEqual(
        validateReleaseMetadata({ ...metadata, githubRepository: process.env.GITHUB_REPOSITORY }),
      )
    } finally {
      await fs.rm(projectRoot, { recursive: true, force: true })
    }
  })

  it("accepts synchronized project metadata", () => {
    expect(validateReleaseMetadata(metadata)).toEqual([])
  })

  it("rejects template placeholders", () => {
    const errors = validateReleaseMetadata({
      ...metadata,
      packageName: "comfyui-custom-node-template",
      repository: "https://github.com/your-name/your-repo",
      publisherId: "your-username",
    })
    expect(errors.length).toBeGreaterThanOrEqual(3)
  })

  it("rejects mismatched package, source, display, and repository identities", () => {
    const errors = validateReleaseMetadata({
      ...metadata,
      packageName: "different-package",
      frontendProjectId: "different-frontend",
      backendProjectId: "different-backend",
      frontendProjectName: "Different Frontend",
      backendProjectName: "Different Backend",
      githubRepository: "craftingmod/different-repository",
    })
    expect(errors).toHaveLength(6)
  })
})
