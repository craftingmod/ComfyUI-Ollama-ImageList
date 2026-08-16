import { describe, expect, it } from "bun:test"

import { EXTENSION_NAMES, PROJECT_ID, PROJECT_NAME } from "../src/constants.ts"

describe("project identity constants", () => {
  it("matches Registry metadata and namespaces frontend extensions", () => {
    expect(PROJECT_ID).toBe("ollama-image-list")
    expect(PROJECT_NAME).toBe("Ollama-ImageList")
    expect(EXTENSION_NAMES.CONNECTIVITY).toStartWith(`${PROJECT_ID}.`)
    expect(EXTENSION_NAMES.LLAMA_CPP_WIDGET_STATES).toStartWith(`${PROJECT_ID}.`)
  })
})
