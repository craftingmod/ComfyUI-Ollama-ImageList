import { describe, expect, it } from "bun:test"

import { parseModels } from "../src/ollama-connectivity.ts"

describe("Ollama connectivity response parsing", () => {
  it("accepts a list of model names", () => {
    expect(parseModels({ models: ["gemma3:latest", "qwen3-vl:8b"] })).toEqual([
      "gemma3:latest",
      "qwen3-vl:8b",
    ])
  })

  it("rejects missing or mixed-type model lists", () => {
    expect(() => parseModels({})).toThrow("invalid Ollama model list")
    expect(() => parseModels({ models: ["gemma3:latest", 3] })).toThrow("invalid Ollama model list")
  })
})
