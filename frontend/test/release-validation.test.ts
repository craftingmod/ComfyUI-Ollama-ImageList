import { describe, expect, it } from "bun:test"

import { validateReleaseMetadata } from "../../scripts/validate-release.ts"

const metadata = {
  packageName: "ollama-image-list",
  projectName: "ollama-image-list",
  repository: "https://github.com/craftingmod/ComfyUI-Ollama-ImageList",
  publisherId: "alyac",
  displayName: "Ollama-ImageList",
  icon: "https://cdn.jsdelivr.net/gh/craftingmod/ComfyUI-Ollama-ImageList/assets/icon.svg",
  frontendProjectId: "ollama-image-list",
  frontendProjectName: "Ollama-ImageList",
  backendProjectId: "ollama-image-list",
  backendProjectName: "Ollama-ImageList",
  githubRepository: "craftingmod/ComfyUI-Ollama-ImageList",
}

describe("release metadata validation", () => {
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
