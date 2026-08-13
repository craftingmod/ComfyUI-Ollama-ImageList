import { createEmptyDirectorState, type DirectorState, type MediaItem } from "./types";
import { validateDirectorState, type DirectorValidationResult } from "./validation";

const MAX_DIRECTOR_STATE_CHARACTERS = 1_000_000;

function stableItems(items: Record<string, MediaItem>): Record<string, MediaItem> {
  return Object.fromEntries(Object.keys(items).sort().map((id) => [id, items[id] as MediaItem]));
}

export function serializeDirectorState(state: DirectorState): string {
  const validated = validateDirectorState(state).state;
  return JSON.stringify({ ...validated, items: stableItems(validated.items) });
}

export function deserializeDirectorState(value: unknown): DirectorValidationResult {
  if (typeof value === "string" && value.length > MAX_DIRECTOR_STATE_CHARACTERS) {
    return {
      state: createEmptyDirectorState(),
      issues: ["State JSON exceeded the 1,000,000-character limit."],
      migrated: false,
    };
  }
  if (typeof value !== "string" || value.trim() === "") {
    return validateDirectorState(value ?? createEmptyDirectorState());
  }
  try {
    return validateDirectorState(JSON.parse(value) as unknown);
  } catch (error) {
    return {
      state: createEmptyDirectorState(),
      issues: [`State JSON could not be parsed: ${error instanceof Error ? error.message : "unknown error"}.`],
      migrated: false,
    };
  }
}
