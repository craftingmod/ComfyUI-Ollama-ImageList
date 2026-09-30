# makoto-decision: llama-server Backend Implementation Plan

## 1. Goal

Add a `llama-server` backend to `makoto-decision` so that Jev-like decision primitives such as:

- `Noul`
- `Choice`
- `Score`
- `NDigit`

can be evaluated through a running `llama-server` instance.

The implementation should **not** pretend that `llama-server` exposes raw prefill logits.

Instead, introduce a backend abstraction based on **candidate probability evaluation**.

---

## 2. Core Design Principle

There are two fundamentally different evaluation paths.

### llama-cpp-python backend

```text
prompt
  ↓
prefill
  ↓
raw final-position logits
  ↓
candidate token scores
  ↓
softmax
  ↓
probabilities
```

### llama-server backend

```text
prompt
  ↓
/completion
  ↓
grammar-constrained 1-token decoding
  ↓
top candidate probabilities
  ↓
candidate mapping
  ↓
renormalization
  ↓
probabilities
```

These two mechanisms should share a common abstraction at the **candidate distribution** level, not at the raw-logit level.

Avoid:

```text
Decision
  ↓
RawLogitsEvaluator
  ├─ llama-cpp-python
  └─ llama-server  ← forced abstraction
```

Prefer:

```text
Decision
  ↓
CandidateEvaluator
  ├─ LlamaCppEvaluator
  └─ LlamaServerEvaluator
```

---

## 3. Proposed Public/Internal Interface

Prefer an evaluator interface that returns normalized candidate probabilities.

```python
from typing import Mapping, Protocol, Sequence


class CandidateEvaluator(Protocol):
    def probabilities(
        self,
        prompt: str,
        candidates: Sequence[str],
    ) -> Mapping[str, float]: ...
```

This gives all higher-level decision APIs one common contract.

```text
Choice
Noul
Score
NDigit
   │
   ▼
CandidateEvaluator.probabilities(...)
```

The decision layer should not need to know whether the backend used:

- raw logits,
- logprobs,
- constrained decoding,
- HTTP,
- local Python bindings,
- or a future external provider.

---

## 4. Existing llama-cpp-python Backend

The current local evaluator can remain conceptually equivalent to:

```python
def probabilities(
    self,
    prompt: str,
    candidates: Sequence[str],
) -> Mapping[str, float]:
    result = self.llama.create_chat_prefill(...)

    candidate_logits = extract_candidate_logits(
        logits=result.logits,
        candidates=candidates,
    )

    return softmax(candidate_logits)
```

Its semantics are:

```text
prefill-only
→ raw next-token logits
→ candidate extraction
→ probability normalization
```

This remains the highest-fidelity local backend when direct logits are available.

---

## 5. New LlamaServerEvaluator

Introduce something similar to:

```python
class LlamaServerEvaluator:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def probabilities(
        self,
        prompt: str,
        candidates: Sequence[str],
    ) -> Mapping[str, float]: ...
```

The evaluator performs the following steps.

```text
semantic candidates
    ↓
assign single-token labels
    ↓
compile decision prompt
    ↓
build grammar
    ↓
POST /completion
    ↓
read returned candidate probabilities
    ↓
map labels back to semantic candidates
    ↓
renormalize
```

---

## 6. Candidate Label Assignment

Do not initially send arbitrary semantic choices directly as completion candidates.

For example:

```python
choices = [
    "continue",
    "retry",
    "abort",
]
```

Map them to short labels:

```text
A = continue
B = retry
C = abort
```

Prompt example:

```text
Choose exactly one answer.

A: continue
B: retry
C: abort

Answer:
```

This reduces problems caused by:

- multi-token candidate strings,
- unequal token lengths,
- tokenizer-specific segmentation,
- prefix overlap.

The first implementation should require every generated label to correspond to exactly one model token.

---

## 7. Grammar-Constrained Decoding

Generate a grammar that allows only the assigned labels.

Example:

```text
root ::= "A" | "B" | "C"
```

Then call `/completion` with one generated token.

Conceptual request:

```json
{
  "prompt": "...",
  "n_predict": 1,
  "temperature": 1.0,
  "top_k": 0,
  "top_p": 1.0,
  "min_p": 0.0,
  "typical_p": 1.0,
  "repeat_penalty": 1.0,
  "presence_penalty": 0.0,
  "frequency_penalty": 0.0,
  "dry_multiplier": 0.0,
  "xtc_probability": 0.0,
  "mirostat": 0,
  "n_probs": 3,
  "post_sampling_probs": true,
  "grammar": "root ::= \"A\" | \"B\" | \"C\""
}
```

Use a nonzero temperature when returning post-sampling probabilities; `temperature: 0` is greedy and can collapse the returned candidate distribution to a one-hot result. Disable truncating and penalty samplers so the probabilities reflect the requested candidate set before the evaluator renormalizes them.

The exact request/response schema must be verified against the supported `llama.cpp` version.

The backend should isolate this protocol detail from the rest of `makoto-decision`.

---

## 8. Probability Extraction

Conceptually, the server response may expose data similar to:

```json
{
  "probs": [
    {
      "top_probs": [
        {"token": "B", "prob": 0.71},
        {"token": "A", "prob": 0.21},
        {"token": "C", "prob": 0.08}
      ]
    }
  ]
}
```

Convert that into:

```python
{
    "continue": 0.21,
    "retry": 0.71,
    "abort": 0.08,
}
```

Recommended helper:

```python
def map_label_probabilities(
    labels: Mapping[str, str],
    returned: Mapping[str, float],
) -> dict[str, float]: ...
```

Where:

```python
labels = {
    "A": "continue",
    "B": "retry",
    "C": "abort",
}
```

---

## 9. Renormalization

Even when probabilities are returned by the server, normalize them over the requested decision candidates.

```python
def normalize(
    values: Mapping[str, float],
) -> dict[str, float]:
    total = sum(values.values())

    if total <= 0.0:
        raise ValueError("Candidate probabilities contain no positive mass")

    return {key: value / total for key, value in values.items()}
```

This makes the public decision result consistently represent:

```text
P(candidate | candidate set)
```

rather than probability mass over the complete vocabulary.

---

## 10. Missing Candidate Handling

Do not assume that every candidate will always appear in the returned top probability list.

Implement explicit handling.

```python
candidate_labels = {"A", "B", "C"}
returned_labels = {"A", "B"}

missing = candidate_labels - returned_labels
```

Initial policy:

```text
missing candidate
→ assign probability 0.0
→ renormalize returned candidate mass
```

Example:

```python
raw = {
    "A": 0.20,
    "B": 0.70,
    "C": 0.00,
}

normalized = {
    "A": 0.2222,
    "B": 0.7778,
    "C": 0.0000,
}
```

However, also expose enough diagnostics to detect unexpected omissions during testing.

For example:

```python
@dataclass(frozen=True)
class EvaluationDiagnostics:
    missing_labels: tuple[str, ...] = ()
```

This can remain internal initially.

---

## 11. Noul

`Noul` should be implemented as a specialization of the same candidate mechanism.

Example:

```text
A = yes
B = no
```

Internally:

```python
distribution = evaluator.probabilities(
    prompt,
    ["yes", "no"],
)
```

Then:

```python
answer = max(distribution, key=distribution.get)
confidence = distribution[answer]
```

No dedicated `llama-server` logic should be required.

---

## 12. Choice

`Choice` is the generic N-way case.

```python
distribution = evaluator.probabilities(
    prompt,
    choices,
)
```

Return:

```python
ChoiceResult(
    choice=max(distribution, key=distribution.get),
    probabilities=distribution,
)
```

Keep semantic candidate labels independent from the generated A/B/C/... labels.

---

## 13. Score

`Score` can also reuse `Choice`.

For example:

```python
scores = ["0", "1", "2", "3", "4"]
distribution = evaluator.probabilities(
    prompt,
    scores,
)
```

Then optionally compute an expected score:

```python
expected_score = sum(
    float(score) * probability for score, probability in distribution.items()
)
```

For ordinal decisions, preserve the complete distribution rather than returning only the expected value.

Example:

```python
ScoreResult(
    score=3,
    expected_score=2.74,
    probabilities={
        0: 0.01,
        1: 0.07,
        2: 0.25,
        3: 0.47,
        4: 0.20,
    },
)
```

---

## 14. NDigit

`NDigit` should preferably not become a completely separate evaluator path.

Treat it as a numeric candidate specialization.

Example:

```python
digits = [str(i) for i in range(10)]

distribution = evaluator.probabilities(
    prompt,
    digits,
)
```

Equivalent candidate space:

```text
0
1
2
3
4
5
6
7
8
9
```

Grammar:

```text
root ::= "0" | "1" | "2" | "3" | "4"
       | "5" | "6" | "7" | "8" | "9"
```

If `n_digit` means a custom digit range, build the candidate set dynamically.

Example:

```python
def digit_candidates(n: int) -> list[str]:
    return [str(i) for i in range(n)]
```

For the first implementation, restrict this feature to values that can be represented safely by the chosen single-token labeling strategy.

---

## 15. Label Generation

Do not hard-code only `A` through `Z` without considering larger candidate sets.

Provide a label allocator.

Possible initial implementation:

```text
A
B
C
...
Z
```

If the candidate count exceeds the supported single-token label pool, fail explicitly:

```python
raise ValueError("Too many candidates for the current single-token label strategy")
```

Do not silently switch to:

```text
AA
AB
AC
```

unless multi-token labels are deliberately supported later.

The evaluator should verify label tokenization against the target server/model when necessary.

---

## 16. Recommended Internal Components

Suggested module structure:

```text
makoto_decision/
├── decision.py
├── result.py
├── evaluator/
│   ├── __init__.py
│   ├── protocol.py
│   ├── llama_cpp.py
│   └── llama_server.py
└── internal/
    ├── labels.py
    ├── grammar.py
    ├── normalize.py
    └── prompt.py
```

Possible responsibilities:

### `evaluator/protocol.py`

```python
class CandidateEvaluator(Protocol):
    def probabilities(...):
        ...
```

### `evaluator/llama_cpp.py`

```text
prefill
→ logits
→ candidate probabilities
```

### `evaluator/llama_server.py`

```text
HTTP request
→ constrained one-token decode
→ candidate probabilities
```

### `internal/labels.py`

```text
candidate ↔ generated label mapping
```

### `internal/grammar.py`

```text
candidate label grammar generation
```

### `internal/normalize.py`

```text
softmax / probability renormalization
```

### `internal/prompt.py`

```text
decision prompt construction
```

---

## 17. HTTP Dependency

`makoto-decision` is currently intended to remain lightweight.

Avoid introducing a large HTTP framework dependency solely for the server backend.

Possible options:

### Option A — stdlib `urllib`

Pros:

- zero external dependencies,
- suitable for a tiny library.

Cons:

- somewhat verbose.

### Option B — optional `httpx`

Pros:

- clean API,
- easy timeout/error handling,
- async support later.

Cons:

- adds an optional dependency.

Recommended first implementation:

```text
stdlib HTTP implementation
```

or:

```text
optional extra:

makoto-decision[llama-server]
```

if the project already accepts optional dependency groups.

Do not make an HTTP package mandatory for users who only use `llama-cpp-python`.

---

## 18. Server Errors

Convert transport/protocol failures into explicit backend errors.

Suggested hierarchy:

```python
class DecisionEvaluationError(RuntimeError):
    pass


class LlamaServerError(DecisionEvaluationError):
    pass


class LlamaServerProtocolError(LlamaServerError):
    pass
```

Handle at least:

- connection refused,
- timeout,
- non-2xx status,
- malformed JSON,
- missing probability fields,
- missing generated token,
- invalid candidate label,
- zero total candidate probability.

Do not silently return arbitrary fallback distributions.

---

## 19. Capability Semantics

Do not claim that both evaluators provide identical raw evidence.

They provide the same **decision-level contract**, but use different mechanisms.

Possible metadata:

```python
class EvaluationMethod(Enum):
    RAW_LOGITS = "raw_logits"
    CONSTRAINED_COMPLETION = "constrained_completion"
```

This does not necessarily need to be public in the first release.

It may be useful for:

- debugging,
- benchmarks,
- future calibration,
- reproducibility.

---

## 20. Sampling Configuration

For decision evaluation, avoid ordinary creative sampling.

Recommended defaults:

```text
n_predict = 1
grammar = candidate labels only
post_sampling_probs = true
temperature = 1.0
top_k = 0
top_p = 1.0
min_p = 0.0
```

Temperature and other sampling parameters should be treated carefully.

The evaluator should aim to expose the underlying candidate distribution, not randomly select a completion.

Where supported, configure the server so that probability extraction remains deterministic and minimally transformed.

Do not assume that the probability semantics are identical to raw logits.

---

## 21. Bias and Calibration

Single-token labels introduce possible label prior bias.

Example:

```text
A = continue
B = retry
C = abort
```

may not be numerically identical to:

```text
A = abort
B = continue
C = retry
```

This should not block the first implementation.

Initial version:

```text
single assignment
→ constrained probabilities
```

Possible future calibration:

```text
candidate permutation
→ repeated evaluation
→ map probabilities back to semantic candidates
→ average
```

Example:

```text
run 1:
A = continue
B = retry
C = abort

run 2:
A = retry
B = abort
C = continue

run 3:
A = abort
B = continue
C = retry
```

This can reduce token/position bias at the cost of additional server calls.

Keep this outside the minimum viable implementation.

---

## 22. Multimodal Advantage

A major advantage of the server backend is that multimodal support can remain inside `llama-server`.

Conceptually:

```text
ComfyUI
  ↓
llama-server
  ├─ text
  ├─ image / MTMD processing
  └─ decision completion
```

This avoids making `makoto-decision` directly manage:

- MTMD contexts,
- multimodal tokenization,
- multimodal KV state,
- backend-specific C bindings.

The evaluator should therefore avoid assuming that the incoming request is necessarily text-only forever.

For the initial implementation, text prompt support is sufficient, but keep the transport abstraction extensible.

---

## 23. Suggested API Usage

Example:

```python
from makoto_decision import Choice
from makoto_decision.evaluator import LlamaServerEvaluator


evaluator = LlamaServerEvaluator(
    "http://127.0.0.1:8080",
)

result = Choice(
    evaluator=evaluator,
    prompt="What should the workflow do next?",
    choices=[
        "continue",
        "retry",
        "abort",
    ],
).evaluate()
```

Expected conceptual result:

```python
ChoiceResult(
    choice="retry",
    probabilities={
        "continue": 0.21,
        "retry": 0.71,
        "abort": 0.08,
    },
)
```

The caller should not care whether those probabilities came from:

```text
llama-cpp-python prefill logits
```

or:

```text
llama-server constrained completion
```

---

## 24. Testing Plan

### Unit tests

Test independently:

```text
label allocation
grammar generation
server response parsing
missing candidate handling
probability normalization
semantic label remapping
HTTP error conversion
```

Use fake server responses rather than requiring a live model.

Example cases:

```text
3 candidates returned normally
candidate returned out of order
one candidate omitted
zero probability candidate
unknown label returned
malformed response
HTTP timeout
HTTP 500
```

### Integration tests

Optional tests requiring a real `llama-server`.

Verify:

1. server starts,
2. model loads,
3. candidate grammar is accepted,
4. exactly one valid label is generated,
5. probabilities can be extracted,
6. probability sum after normalization is approximately 1,
7. semantic candidate mapping is stable.

### Cross-backend tests

For simple prompts, compare:

```text
LlamaCppEvaluator
vs
LlamaServerEvaluator
```

Do **not** require exact equality.

Instead verify broad properties:

```text
same candidate set
valid finite probabilities
sum ≈ 1
winner usually consistent on clear prompts
```

The two backends are not mathematically identical.

---

## 25. Implementation Order

### Phase 1 — abstraction

Introduce:

```python
CandidateEvaluator
```

and refactor existing decision primitives to consume candidate probabilities.

Do not change behavior of the existing backend.

### Phase 2 — local backend adaptation

Wrap existing `llama-cpp-python` logic behind:

```python
CandidateEvaluator.probabilities()
```

Confirm all existing tests still pass.

### Phase 3 — label and grammar helpers

Implement:

```text
assign_labels()
build_candidate_grammar()
compile_choice_prompt()
```

with unit tests.

### Phase 4 — llama-server transport

Implement:

```python
LlamaServerEvaluator
```

with mocked HTTP tests.

### Phase 5 — live integration test

Verify against a real local `llama-server`.

### Phase 6 — NDigit / Score specialization

Build these on top of the same candidate evaluator.

Do not create separate server-specific code paths.

### Phase 7 — optional calibration

Only after the basic backend is stable, consider:

```text
label permutation averaging
```

or other bias-reduction strategies.

---

## 26. Non-Goals for Initial Implementation

Do not initially implement:

- arbitrary multi-token semantic candidate scoring,
- KV cache management through the server,
- raw vocabulary logits through undocumented endpoints,
- server lifecycle management,
- model downloading,
- llama-server process spawning,
- candidate permutation calibration,
- distributed/multi-server routing.

`makoto-decision` should consume an already available decision backend.

Process lifecycle belongs to the host application, such as the ComfyUI integration layer.

---

## 27. Final Architecture

Target architecture:

```text
                 makoto-decision
                       │
            ┌──────────┴──────────┐
            │                     │
          Noul                  Choice
            │                     │
            ├──────────┬──────────┤
            │          │          │
          Score      NDigit      ...
            │          │
            └────┬─────┘
                 │
                 ▼
         CandidateEvaluator
                 │
        ┌────────┴────────┐
        │                 │
        ▼                 ▼
LlamaCppEvaluator   LlamaServerEvaluator
        │                 │
        ▼                 ▼
 prefill/logits      /completion
        │            grammar + 1 token
        ▼                 ▼
 candidate logits   candidate probabilities
        │                 │
        └────────┬────────┘
                 ▼
       normalized distribution
                 │
                 ▼
           DecisionResult
```

The most important rule is:

> `llama-server` is a candidate-probability backend, not a fake raw-logits backend.

Keeping that boundary explicit should allow `makoto-decision` to support both the current `llama-cpp-python` implementation and future external inference backends without repeatedly redesigning the decision API.
