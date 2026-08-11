# 작업: 기존 llama.cpp 생성 노드에 LlamaNGramMapDecoding 지원 추가

현재 프로젝트에는 `llama-cpp-python`의 `Llama`를 이용하는 일반 text/multimodal
생성 노드가 이미 구현되어 있다.

기존 생성 동작과 UI 호환성을 유지하면서, 공식 `llama-cpp-python`에 포함된
`LlamaNGramMapDecoding`을 선택적으로 사용할 수 있도록 구현한다.

## 목표

기존 일반 생성 노드에 다음 speculative mode를 추가한다.

- `off`
- `ngram`

`ngram` 모드는 별도의 draft GGUF를 사용하지 않는다. 현재 prompt 및 생성된 token
history의 반복 패턴을 이용하는 `LlamaNGramMapDecoding`을 `Llama(draft_model=...)`에
전달한다.

Native DFlash/DSpark는 이 작업 범위에 포함하지 않는다. 별도의 Experimental 노드로
유지한다.

## API

다음 공식 API를 사용한다.

```python
from llama_cpp.llama_speculative import LlamaNGramMapDecoding
```

기본 연결 예시:

```python
draft_model = None

if speculative_mode == "ngram":
    draft_model = LlamaNGramMapDecoding(
        ngram_size=ngram_size,
        num_pred_tokens=num_pred_tokens,
        mode=ngram_mode,
        min_hits=ngram_min_hits,
        max_entries_per_key=max_entries_per_key,
        sync_check_tokens=sync_check_tokens,
    )

llm = Llama(
    **model_kwargs,
    draft_model=draft_model,
)
```

## UI 입력

기존 노드에 다음 입력을 추가한다.

| 이름 | 형식 | 기본값 | 범위 또는 선택지 |
|---|---|---:|---|
| `speculative_mode` | combo | `off` | `off`, `ngram` |
| `ngram_size` | integer | `3` | 1–8 |
| `num_pred_tokens` | integer | `10` | 1–32 |
| `ngram_mode` | combo | `k` | `k`, `k4v` |
| `ngram_min_hits` | integer | `2` | 1–16 |
| `ngram_max_entries_per_key` | integer | `8` | 0–1024 |
| `ngram_sync_check_tokens` | integer | `16` | 1–256 |

`ngram_max_entries_per_key=0`은 Python API의 `None`으로 변환한다.

```python
max_entries_per_key = (
    None
    if ngram_max_entries_per_key == 0
    else ngram_max_entries_per_key
)
```

가능하다면 프런트엔드에서 `speculative_mode != "ngram"`일 때 세부 n-gram 입력을
숨기거나 비활성화한다. 프런트엔드 확장이 필요하거나 복잡해진다면 항상 표시해도 괜찮다.
backend에서는 mode가 `off`일 때 해당 값을 무시한다.

## 기본 동작 보존

`speculative_mode="off"`일 때는 기존 코드와 완전히 동일하게 동작해야 한다.

- draft 객체를 만들지 않는다.
- `draft_model=None`을 전달하거나 기존 코드가 인자를 생략했다면 그대로 생략한다.
- 기존 text, image, audio/video 입력 처리에 변화를 주지 않는다.
- 기존 sampling 기본값과 결과 처리 방식을 변경하지 않는다.
- Native DFlash/DSpark 관련 fork wheel을 요구하지 않는다.

## Import 및 버전 호환성

노드 모듈 전체가 import 실패하지 않도록 `LlamaNGramMapDecoding`은 필요할 때 lazy
import한다.

```python
def create_ngram_draft(...):
    try:
        from llama_cpp.llama_speculative import LlamaNGramMapDecoding
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "N-gram speculative decoding is unavailable in the installed "
            "llama-cpp-python package. Upgrade llama-cpp-python or set "
            "speculative_mode to 'off'."
        ) from exc

    return LlamaNGramMapDecoding(...)
```

일반 노드 등록 자체는 이 import 실패 때문에 중단되면 안 된다. `ngram`을 실제로
선택했을 때만 명확한 오류를 낸다.

## 객체 수명

현재 노드가 요청마다 `Llama`를 생성하고 종료한다면 draft 객체도 요청 지역 객체로
생성한다.

```python
llm = Llama(..., draft_model=draft_model)

try:
    response = llm.create_chat_completion(...)
finally:
    llm.close()
```

동일한 `LlamaNGramMapDecoding` 인스턴스를 서로 무관한 요청이나 여러 `Llama` 인스턴스에
무기한 공유하지 않는다.

기존 노드가 같은 `Llama` 및 draft 인스턴스를 재사용한다면 완전히 새로운 대화나
unrelated prompt를 시작하기 전에 다음을 호출한다.

```python
draft_model.clear()
```

단순한 동일 context 연속 생성에서는 내부 index 재사용이 목적에 맞을 수 있으므로 무조건
매 호출마다 clear하지 말고, 기존 노드의 context reset 정책과 맞춘다.

## 입력 검증

backend에서도 다음을 검증한다.

```python
if not 1 <= ngram_size <= 8:
    raise ValueError("ngram_size must be between 1 and 8")

if not 1 <= num_pred_tokens <= 32:
    raise ValueError("num_pred_tokens must be between 1 and 32")

if ngram_mode not in {"k", "k4v"}:
    raise ValueError("ngram_mode must be 'k' or 'k4v'")

if ngram_min_hits < 1:
    raise ValueError("ngram_min_hits must be at least 1")

if ngram_sync_check_tokens < 1:
    raise ValueError("ngram_sync_check_tokens must be at least 1")
```

지원하는 실제 constructor signature를 현재 설치된 `llama-cpp-python` 소스에서 확인한다.
API에 존재하지 않는 인자를 추측해서 전달하지 않는다.

## 사용자 설명

UI tooltip 또는 노드 문서에 다음 취지의 설명을 추가한다.

> N-gram speculative decoding predicts candidate tokens from repeated patterns
> already present in the prompt and generated context. It requires no additional
> GGUF model and uses little additional VRAM. Speedup depends on repetition and
> is most likely for code, JSON, templates, and boilerplate text. It may provide
> little or no benefit for short or non-repetitive natural-language responses.

이 기능은 결과 정확도를 낮춰 빠르게 만드는 옵션으로 설명하지 않는다. 후보 token은 target
모델이 검증하며, 실제 성능은 acceptance와 workload에 따라 달라진다.

## 통계 및 로그

`LlamaNGramMapDecoding`에 native DFlash와 같은 `draft.stats`가 있다고 가정하지 않는다.

현재 공개 API에서 안정적으로 제공되는 통계가 없다면 임의로 내부 필드를 읽지 않는다. 대신
다음 정도만 로그에 남긴다.

```text
speculative mode: ngram
ngram size: 3
max predicted tokens: 10
mode: k
minimum hits: 2
```

기존 노드에 generation time 또는 token/s 측정이 있다면 그대로 사용해 `off`와 `ngram`을
비교할 수 있게 한다.

## 테스트

실제 대형 GGUF가 없어도 실행 가능한 단위 테스트를 추가한다.

최소 테스트:

1. `speculative_mode="off"`일 때 draft 객체를 생성하지 않는다.
2. `off`일 때 기존 `Llama` 인자가 변하지 않는다.
3. `ngram`일 때 `LlamaNGramMapDecoding`이 한 번 생성된다.
4. 모든 n-gram 파라미터가 올바르게 전달된다.
5. `max_entries_per_key=0`이 `None`으로 변환된다.
6. 생성된 draft 객체가 `Llama(draft_model=...)`에 전달된다.
7. import 실패 시 노드 등록은 유지되고, `ngram` 실행에서만 명확한 오류가 발생한다.
8. 생성 성공과 예외 상황 모두에서 기존 `llm.close()`가 호출된다.
9. `speculative_mode="off"`인 기존 workflow 입력이 계속 실행된다.
10. multimodal 요청에서도 기존 message와 `mmproj_path` 구성이 변하지 않는다.

fake 또는 monkeypatch된 `Llama`와 `LlamaNGramMapDecoding`을 사용한다. 단위 테스트에서
CUDA나 실제 GGUF를 요구하지 않는다.

## 수동 스모크 테스트

반복이 많은 prompt로 `off`와 `ngram`을 각각 실행한다.

예시:

```text
Create Python CRUD functions for users, products, orders, and invoices.
Each section must use the same function structure and error-handling pattern.
```

비교 항목:

- 양쪽 모두 정상적인 응답 반환
- `finish_reason` 정상
- 빈 응답이나 예외 없음
- 동일한 `max_tokens`, seed 및 sampling 설정 사용
- generation time과 token/s 기록

token-exact 일치를 필수 조건으로 두지 않는다. 다만 출력이 손상되거나 반복 루프에 빠지지
않는지 확인한다.

## 비목표

다음은 이번 작업에서 구현하지 않는다.

- Native DFlash/DSpark
- 별도 draft GGUF selector
- experimental fork wheel 설치
- custom acceptance 통계
- continuous batching 구조 변경
- generation engine 리팩터링
- 새로운 C++ 또는 ctypes ABI
- grammar/sampler 동작 변경

## 완료 조건

- 기존 일반 노드에 `off/ngram` 선택이 추가됨
- `off` 경로의 기존 동작이 보존됨
- `ngram`이 공식 `LlamaNGramMapDecoding`을 통해 `draft_model`에 연결됨
- 실제 모델 없이 수행하는 단위 테스트가 통과함
- 반복 prompt를 이용한 수동 smoke test 절차가 문서화됨
- 변경사항은 아직 commit 또는 stage하지 않음
