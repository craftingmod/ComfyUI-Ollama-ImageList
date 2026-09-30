# Decide sequential implementation plan

## Contract

- Preserve all existing node IDs, single Decide contracts, choice-normalized probability outputs, and session ownership; the runtime probability correction below replaces the inconsistent server post-sampling distribution.
- Name existing Generate Sequential displays explicitly Media Sequential; keep saved IDs and slot order.
- Add `LlamaCppMtmd_DecideMediaSequential`: one decision per atomic IMAGE/AUDIO/VIDEO bundle, preserving IMAGE → AUDIO → VIDEO order and VIDEO-owned audio. `context` and typed `question` each accept one shared value or exactly one value per media item. No media means one text-only decision.
- Add `LlamaCppMtmd_DecidePromptSequential`: normalize the complete media bundle once; execute flat `context` and typed `question` lists in order against that fixed bundle. The execution count is the longer list; each list must have length 1 or the execution count. Pair by index, never form a Cartesian product.
- Keep `system`, `seed`, `model_profile`, and `session_unload` scalar. Validate every context/question and list length before inference. Question/answers remain text-only.
- Return parallel lists for `selected`, `probabilities_json`, `metrics_json`, and `media_diagnostics`; return one scalar `session` handle. Unload once after the complete sequence when requested.
- Prompt Sequential adds `reuse_kv_cache=True`; media precedes variable context/question independently of this toggle. Native skips the outer reset and delegates prefix synchronization to the public prefill API. Server explicitly sends `cache_prompt` true/false. Legacy calls retain their defaults.
- KV reuse is best effort: handler prefill, templates, hybrid/recurrent checkpoints, and installed wheel/server support determine actual reuse. Media decoding/encoding can repeat. Do not retry failed inference or manipulate private library KV state.

## Owners and sequence

### Runtime probability correction (2026-10-01)

- `cache_backend` (Luna MAX): fix the shared server Decide scorer. Request the complete pre-sampling vocabulary distribution, retain only the canonical decision IDs, and require every choice to be present before normalization. Non-choice candidates such as Gemma 4 `<|channel>` do not invalidate a valid decision.
- `review_docs` (Luna MAX): independently review the server metadata, probability schema, missing-choice handling, and response-cost implications without executing validation.
- Parent: review the final edits and update this status. Preserve single and Sequential node contracts, session ownership, and cache options. Do not synthesize missing probabilities or retry inference.
- Server scoring will use pre-sampling probabilities renormalized over the choices, rather than the previous sampling-dependent distribution. Native scoring is unchanged. Full-vocabulary responses increase transfer and parsing cost; runtime behavior remains unverified until explicitly requested.

1. Parent: inspect the current dirty worktree, record this plan, coordinate the existing Luna MAX agents, and review final changes without executing validation.
2. `cache_backend`: extend Native/Runtime/Connect `decide()` and media prefill adaptation with request-scoped cache/order options; add focused backend coverage without running it.
3. `prompt_node`: share existing Decide schema/request/output helpers where useful; add both nodes, register them, update Generate Media Sequential display names, and add focused node/registration coverage without running it.
4. `review_docs`: verify official ComfyUI list/schema and llama.cpp cache documentation, review implementation independently, and update user/testing/status documentation.
5. Parent: reconcile findings and mark implementation status here. Preserve all earlier Generate Prompt Sequential changes.

## Stop rules and verification

- Do not run tests, lint, builds, or live runtime validation unless explicitly requested. Future requested tests use `bun run test:agent`.
- If public native prefill resets internally, document that reuse may be unavailable; do not patch an external checkout or emulate prefill logits.
- Current local text chat prefill calls `llama.prefill(..., reset=True)` and therefore resets internally; skipping the repository reset only enables actual reuse for prefix-aware handlers such as the current MTMD prefill path.
- Add runnable checks for list pairing/broadcast, rejection before execution, atomic media pairing, fixed bundle reuse, single session output, final unload, legacy defaults, cache true/false, and independent message order.
- Actual Native GGUF/MTMD/hybrid and server cache-hit/performance checks remain pending; manual procedures belong in `docs/TESTING.md`.

## Status

- Plan recorded; Native/server Decide cache and media-order options implemented, with focused test coverage added.
- Both Decide Sequential nodes, registration, scalar session ownership, and Generate Media Sequential display renames implemented.
- Dedicated execution tests added for media ownership, both broadcast directions, fixed-bundle prompt pairing, cache control, scalar session output, final unload, and rejection before inference.
- Parent and independent source reviews completed; no actionable correctness issues remain.
- Validation intentionally not run.
- Actual ComfyUI, GGUF/MTMD/hybrid, server cache-hit, and performance checks remain unverified.
- First runtime feedback exposed the server Decide path's hard-coded media marker. Media template requests now use structured image/audio/video parts so `/apply-template` inserts the server's active marker; regression coverage models a randomized server marker. Validation remains unrun.
- Gemma 4 probability feedback exposed unrelated `<|channel>` candidates in post-sampling output. The shared server Decide scorer now requests full-vocabulary pre-sampling logprobs, requires every canonical choice ID, and normalizes only those choices. Luna MAX implementation and independent source-contract review are complete; focused regression cases were added but not executed. Full-vocabulary transfer cost and live Gemma 4 behavior remain unverified.
