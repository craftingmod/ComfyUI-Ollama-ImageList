# ComfyUI Native Speculative 연결 가이드

## 목적

이미 `llama-cpp-python`의 `Llama`를 이용해 text 또는 multimodal 생성을 수행하는
ComfyUI 노드에 experimental native speculative decoding을 선택적으로 연결한다.

이 문서는 새 생성 노드를 처음부터 구현하는 방법이 아니라 다음 항목만 다룬다.

- draft/speculative GGUF 선택
- speculative 파라미터를 Python API에 연결
- `Llama`와 draft 객체의 생성 및 해제 순서
- 실행 통계 노출
- 현재 미지원 조합 차단

## 검증된 사용 범위

- Windows x64
- CPython 3.13
- CUDA 13.2로 빌드한 experimental wheel
- NVIDIA RTX 3090 Ti, SM 8.6
- single request / single sequence
- text 생성
- 초기 single-shot mmproj image prefill
- DFlash draft GGUF
- 생성 후 모델 언로드

현재 wheel의 experimental API는 최상위 `llama_cpp` namespace에 export되지 않는다.

```python
from llama_cpp import Llama
from llama_cpp.llama_speculative import LlamaNativeSpeculativeDecoding
```

## 권장 UI 입력

기존 노드에 다음 입력을 추가한다.

| 입력 | 형식 | 기본값 | 설명 |
|---|---|---:|---|
| `native_speculative` | boolean | `False` | experimental 경로 활성화 |
| `draft_model` | GGUF selector | 없음 | DFlash 또는 DSpark draft GGUF |
| `spec_type` | combo | `draft-dflash` | `draft-dflash`, `draft-dspark` |
| `spec_n_max` | integer | `8` | 한 speculative cycle의 최대 draft token 수 |
| `spec_n_min` | integer | `0` | 최소 draft token 수 |
| `spec_p_min` | float | `0.0` | draft confidence threshold |

초기 ComfyUI 통합에서는 `spec_n_max=8`을 보수적인 기본값으로 권장한다.
실험적으로 `15`까지 올릴 수 있지만 acceptance가 낮으면 오히려 비용이 증가할 수 있다.

draft 모델 selector는 일반 target 모델과 분리하는 것이 좋다. 파일명만으로 모델 호환성을
완전히 판별할 수 없으므로 UI에는 다음 경고를 표시한다.

> Experimental: the selected draft GGUF must be compatible with the target
> model. An incompatible pair may fail during initialization or generation.

## 파라미터 연결

기존 `Llama` 생성 코드가 다음 형태라고 가정한다.

```python
llm = Llama(
    model_path=target_model_path,
    mmproj_path=mmproj_path,
    n_gpu_layers=n_gpu_layers,
    n_ctx=n_ctx,
    n_batch=n_batch,
    n_ubatch=n_ubatch,
)
```

speculative 모드에서는 먼저 draft 객체를 만들고 `draft_model` 인자로 전달한다.

```python
draft = LlamaNativeSpeculativeDecoding(
    model_path=draft_model_path,
    spec_type=spec_type,
    n_gpu_layers=n_gpu_layers,
    n_max=spec_n_max,
    n_min=spec_n_min,
    p_min=spec_p_min,
)

llm = Llama(
    model_path=target_model_path,
    mmproj_path=mmproj_path,
    draft_model=draft,
    n_gpu_layers=n_gpu_layers,
    n_ctx=n_ctx,
    n_batch=n_batch,
    n_ubatch=n_ubatch,
)
```

`mmproj_path`는 vision 요청에만 전달한다. text-only 요청에서는 기존 노드의 동작을
그대로 유지한다.

## 권장 생성 및 정리 구조

draft는 `Llama`보다 먼저 생성한다. 정상적으로 `Llama`가 생성된 뒤에는 `llm.close()`가
연결된 native speculative 자원의 정리를 담당한다.

그러나 `Llama(...)` 생성 자체가 실패하면 소유권 이전이 완료되지 않았을 수 있으므로
draft를 직접 닫아야 한다.

```python
from typing import Any

from llama_cpp import Llama
from llama_cpp.llama_speculative import LlamaNativeSpeculativeDecoding


def run_native_speculative(
    *,
    model_kwargs: dict[str, Any],
    completion_kwargs: dict[str, Any],
    draft_model_path: str,
    spec_type: str = "draft-dflash",
    spec_n_max: int = 8,
    spec_n_min: int = 0,
    spec_p_min: float = 0.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    draft = LlamaNativeSpeculativeDecoding(
        model_path=draft_model_path,
        spec_type=spec_type,
        n_gpu_layers=model_kwargs.get("n_gpu_layers", "all"),
        n_max=spec_n_max,
        n_min=spec_n_min,
        p_min=spec_p_min,
    )

    llm = None
    ownership_transferred = False

    try:
        llm = Llama(**model_kwargs, draft_model=draft)
        ownership_transferred = True

        response = llm.create_chat_completion(**completion_kwargs)

        # close 전에 복사한다. close 이후 native 객체 상태에 접근하지 않는다.
        stats = dict(draft.stats)
        return response, stats
    finally:
        if llm is not None:
            llm.close()
        elif not ownership_transferred:
            draft.close()
```

실제 클래스에 `close()`가 제공되는 현재 experimental wheel을 전제로 한다. 노드가 여러
wheel 버전을 허용한다면 `getattr(draft, "close", None)`로 방어적으로 처리할 수 있다.

```python
close_draft = getattr(draft, "close", None)
if callable(close_draft):
    close_draft()
```

ComfyUI 사용 목적이 load → one generation → unload라면 `Llama` 인스턴스를 전역 cache에
보관하지 않는다. `llm.close()` 후 필요하다면 기존 노드 정책에 맞춰 `gc.collect()` 및
CUDA cache 정리를 수행한다. PyTorch CUDA cache 정리는 llama.cpp가 소유한 allocation을
직접 해제하지 않으므로 반드시 `llm.close()`가 먼저 실행되어야 한다.

## 기존 target-only 경로 보존

speculative가 꺼져 있으면 기존 코드를 그대로 사용한다.

```python
draft = None

if native_speculative:
    if not draft_model_path:
        raise ValueError("Native speculative decoding requires a draft GGUF")

    draft = LlamaNativeSpeculativeDecoding(
        model_path=draft_model_path,
        spec_type=spec_type,
        n_gpu_layers=n_gpu_layers,
        n_max=spec_n_max,
        n_min=spec_n_min,
        p_min=spec_p_min,
    )

llm = Llama(
    **model_kwargs,
    draft_model=draft,
)
```

가능하면 `native_speculative=False`일 때 experimental 모듈을 import하거나 native DLL을
초기화하지 않도록 lazy import를 사용할 수 있다.

```python
if native_speculative:
    from llama_cpp.llama_speculative import LlamaNativeSpeculativeDecoding
```

## 실행 통계

응답 생성 직후, `llm.close()` 전에 다음 통계를 복사한다.

```python
stats = dict(draft.stats)
```

현재 주요 필드는 다음과 같다.

- `draft_calls`
- `accept_calls`
- `drafted_tokens`
- `accepted_tokens`
- `acceptance_rate`
- `mean_accepted_tokens`

ComfyUI 출력 또는 로그에는 최소한 다음 항목을 표시한다.

```text
speculative implementation: draft-dflash
drafted tokens: 1050
accepted tokens: 89
acceptance rate: 8.5%
mean accepted/call: 1.27
```

`draft_calls > 0`과 `drafted_tokens > 0`은 draft 모델이 단순히 로드만 된 것이 아니라
실제 생성에 사용됐다는 기본 증거다.

통계가 없거나 0이면 조용히 성공으로 처리하지 말고 warning을 남긴다.

## 초기 차단 조건

다음 조합에서는 native speculative을 사용하지 않는다.

- grammar 또는 JSON Schema가 지정됨
- custom logits processor가 지정됨
- multi-sequence 또는 continuous batching 요청
- Python state cache 복원이 필요한 요청
- 일반적인 multimodal context shifting이 필요한 요청
- draft GGUF가 선택되지 않음
- experimental API import 실패

구조화 출력 기능이 필요한 기존 노드라면 오류보다는 target-only fallback을 사용할 수 있다.

```python
unsupported_reason = None

if grammar is not None or json_schema is not None:
    unsupported_reason = "grammar/JSON schema"
elif logits_processor is not None:
    unsupported_reason = "custom logits processor"

if native_speculative and unsupported_reason:
    logger.warning(
        "Native speculative decoding does not support %s; falling back to "
        "target-only decoding",
        unsupported_reason,
    )
    native_speculative = False
```

token stopping criteria callback은 현재 native 경로와 회귀 테스트에서 지원한다. 기존 노드가
이를 사용한다면 제거할 필요는 없다. 다만 callback 내부에서 외부 상태를 변경하거나 매 token
마다 큰 배열을 보관하는 특수한 사용법은 별도 검증이 필요하다.

사용자가 experimental 모드를 명시적으로 선택했는데 draft/target 조합이나 ABI가 잘못된
경우에는 target-only로 조용히 fallback하지 않는 편이 좋다. 초기화 실패를 그대로 보여줘야
사용자가 speculative이 적용된 것으로 오해하지 않는다.

## Multimodal 주의사항

vision 입력은 기존 노드가 만드는 multimodal message 형식을 그대로 사용한다.

```python
messages = [
    {
        "role": "user",
        "content": [
            {"type": "image", "image": image_path},
            {"type": "text", "text": prompt},
        ],
    }
]
```

초기 image prefill은 지원하지만 context shifting은 지원하지 않는다. 이미지 token과 prompt가
`n_ctx`를 초과하면 다음 중 하나를 사용한다.

- `n_ctx` 증가
- 이미지 또는 prompt 축소
- target-only fallback

현재 목적에서는 fresh context의 단일 image 요청만 허용하는 것이 가장 안전하다.

짧은 vision 응답은 image encoding과 prefill 비중이 크고 draft acceptance가 낮을 수 있어
실질적인 속도 향상이 없을 수 있다. speculative 활성화 자체와 성능 향상을 구분해서 표시한다.

## 사용자 경고 문구

노드 이름 또는 옵션에 `Experimental`을 포함한다.

```text
Native Speculative Decoding (Experimental)
```

권장 설명:

> Experimental native speculative decoding for compatible DFlash or DSpark
> draft GGUFs. Single-request and single-sequence use only. Unsupported
> combinations may fail or fall back to target-only decoding. Target and draft
> models may consume substantial additional VRAM, and speedup is not guaranteed.

## 최소 테스트 항목

실제 30B 모델을 매번 테스트하지 않도록 Python unit test에서는 fake binding을 사용한다.

1. speculative off 시 기존 `Llama` 인자가 변하지 않는지
2. speculative on 시 draft가 먼저 생성되는지
3. `draft_model`이 `Llama`에 전달되는지
4. `spec_type`, `n_max`, `n_min`, `p_min`이 정확히 전달되는지
5. `Llama` 생성 실패 시 draft가 정리되는지
6. 생성 성공 시 stats를 close 전에 복사하는지
7. grammar 등 미지원 조합에서 target-only fallback 또는 명시적 오류가 발생하는지
8. 실행 후 `llm.close()`가 항상 호출되는지

수동 smoke test는 다음 두 가지면 충분하다.

- text: Muse-Glimmer target + DFlash draft, `draft_calls > 0`
- vision: target + mmproj + DFlash draft, 정상 이미지 설명 및 `finish_reason=stop`

## 현재 검증된 예시 파일

```text
Target:
D:\ComfyUI\models\LLM\Muse-Glimmer\Muse-Glimmer-30B-UD-Q4_K_XL.gguf

Draft:
D:\ComfyUI\models\LLM\Muse-Glimmer\dflash-kquant.gguf

mmproj:
D:\ComfyUI\models\LLM\Muse-Glimmer\mmproj-Muse-Glimmer-30B-Q8_0.gguf
```

이 경로는 검증 환경의 예시이며 노드에 하드코딩하지 않는다. 기존 ComfyUI model selector와
folder registration을 통해 선택하도록 구현한다.
