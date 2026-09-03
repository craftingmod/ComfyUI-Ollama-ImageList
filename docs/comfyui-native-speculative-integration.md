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
- DFlash or DSpark draft GGUF
- 생성 후 모델 언로드

새 API는 최상위 `llama_cpp` namespace가 아니라 `llama_speculative` 모듈에서 가져온다.

```python
from llama_cpp import Llama
from llama_cpp.llama_speculative import SpecConfig, SpeculativeType
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
    n_gpu_layers=n_gpu_layers,
    n_ctx=n_ctx,
    n_batch=n_batch,
    n_ubatch=n_ubatch,
)
```

speculative 모드에서는 공식 `SpecConfig`를 만들고 `Llama(speculative=...)`에 전달한다.

```python
llm = Llama(
    model_path=target_model_path,
    n_gpu_layers=n_gpu_layers,
    n_ctx=n_ctx,
    n_batch=n_batch,
    n_ubatch=n_ubatch,
    speculative=SpecConfig(
        spec_type=SpeculativeType.from_str(spec_type),
        draft_model_path=draft_model_path,
        draft_n_max=spec_n_max,
        draft_n_min=spec_n_min,
        draft_p_min=spec_p_min,
        draft_n_gpu_layers=n_gpu_layers,
        draft_backend_sampling=True,
    ),
)
```

Native speculative 요청은 text-only이므로 이 경로에는 `mmproj_path`를 전달하지 않는다.
비활성화된 target-only 경로는 기존 노드의 multimodal 동작을 그대로 유지한다.

## 권장 생성 및 정리 구조

`SpecConfig`는 모델이나 draft context를 직접 만들지 않는다. `Llama`가 target context를
먼저 초기화한 뒤 선택한 MTP/DFlash/DSpark 엔진과 외부 draft 리소스를 생성하고 소유한다.
따라서 통합 계층은 native engine을 직접 생성하거나 `draft_model=`에 주입하지 않는다.

```python
from llama_cpp import Llama
from llama_cpp.llama_speculative import SpecConfig, SpeculativeType

speculative = SpecConfig(
    spec_type=SpeculativeType.DRAFT_DFLASH,
    draft_model_path=draft_model_path,
    draft_n_max=spec_n_max,
    draft_n_min=spec_n_min,
    draft_p_min=spec_p_min,
    draft_n_gpu_layers="all",
    draft_backend_sampling=True,
)

llm = Llama(
    **model_kwargs,
    speculative=speculative,
)
try:
    response = llm.create_chat_completion(**completion_kwargs)
    stats = dict(llm.last_speculative_stats)
finally:
    llm.close()
```

ComfyUI 사용 목적이 load → one generation → unload라면 `Llama` 인스턴스를 전역 cache에
보관하지 않는다. `llm.close()` 후 필요하다면 기존 노드 정책에 맞춰 `gc.collect()` 및
CUDA cache 정리를 수행한다. PyTorch CUDA cache 정리는 llama.cpp가 소유한 allocation을
직접 해제하지 않으므로 반드시 `llm.close()`가 먼저 실행되어야 한다.

## 기존 target-only 경로 보존

speculative가 꺼져 있으면 기존 코드를 그대로 사용한다.

```python
speculative = None
if native_speculative:
    if not draft_model_path:
        raise ValueError("Native speculative decoding requires a draft GGUF")
    speculative = SpecConfig(
        spec_type=SpeculativeType.from_str(spec_type),
        draft_model_path=draft_model_path,
        draft_n_max=spec_n_max,
        draft_n_min=spec_n_min,
        draft_p_min=spec_p_min,
        draft_n_gpu_layers=n_gpu_layers,
        draft_backend_sampling=True,
    )

llm = Llama(**model_kwargs, speculative=speculative)
```

가능하면 `native_speculative=False`일 때 experimental 모듈을 import하거나 native DLL을
초기화하지 않도록 lazy import를 사용할 수 있다.

```python
if native_speculative:
    from llama_cpp.llama_speculative import SpecConfig, SpeculativeType
```

## 실행 통계

응답 생성 직후, `llm.close()` 전에 다음 통계를 복사한다.

```python
stats = dict(llm.last_speculative_stats)
```

공식 `Llama` 통계의 주요 필드는 다음과 같다. ComfyUI 노드는 여기에 안정적인
`drafted_tokens`, `accepted_tokens`, `acceptance_rate`, `mean_accepted_tokens` 별칭을
추가한다.

- `draft_calls`
- `accept_calls`
- `drafted`
- `accepted_draft_tokens`
- `draft_token_acceptance_rate`
- `mean_accepted_length`

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

다음 조합은 native speculative을 거부한다.

- grammar 또는 JSON Schema가 지정됨
- custom logits processor가 지정됨
- multi-sequence 또는 continuous batching 요청
- Python state cache 복원이 필요한 요청
- IMAGE, AUDIO, or VIDEO 입력
- 외부 provider가 필요한데 draft GGUF가 선택되지 않음
- experimental API import 실패

사용자가 native provider를 명시적으로 선택한 경우 지원되지 않는 입력이나 호환되지 않는
GGUF를 target-only로 조용히 바꾸지 않는다. 입력 검증 또는 `Llama` 초기화 오류를 그대로
표시해 speculative이 실제로 적용되지 않았다는 사실을 숨기지 않는다.

token stopping criteria callback은 현재 native 경로와 회귀 테스트에서 지원한다. 기존 노드가
이를 사용한다면 제거할 필요는 없다. 다만 callback 내부에서 외부 상태를 변경하거나 매 token
마다 큰 배열을 보관하는 특수한 사용법은 별도 검증이 필요하다.

사용자가 experimental 모드를 명시적으로 선택했는데 draft/target 조합이나 ABI가 잘못된
경우에는 target-only로 조용히 fallback하지 않는 편이 좋다. 초기화 실패를 그대로 보여줘야
사용자가 speculative이 적용된 것으로 오해하지 않는다.

## Multimodal 주의사항

현재 공식 stateful MTP/DFlash/DSpark Python 엔진은 text-only이며 `seq_id=0` 한 개만
지원한다. IMAGE, AUDIO, VIDEO 입력은 native speculative과 함께 전달하지 말고, 필요한
경우 일반 target-only 경로를 선택한다. 짧은 텍스트 응답도 draft acceptance와 sidecar
비용에 따라 target-only보다 느릴 수 있으므로 활성화와 성능 향상을 구분해서 표시한다.

## 사용자 경고 문구

노드 이름 또는 옵션에 `Experimental`을 포함한다.

```text
Native Speculative Decoding (Experimental)
```

권장 설명:

> Experimental native speculative decoding for compatible DFlash, DSpark, or MTP
> configurations. Text-only and single-sequence use only. Unsupported combinations
> fail explicitly. Target and draft models may consume substantial additional VRAM,
> and speedup is not guaranteed.

## 최소 테스트 항목

실제 30B 모델을 매번 테스트하지 않도록 Python unit test에서는 fake binding을 사용한다.

1. speculative off 시 기존 `Llama` 인자가 변하지 않는지
2. speculative on 시 `SpecConfig`가 생성되는지
3. `SpecConfig`가 `Llama(speculative=...)`에 전달되는지
4. `spec_type`, `draft_n_max`, `draft_n_min`, `draft_p_min`이 정확히 전달되는지
5. `Llama` 생성 실패가 target-only fallback으로 바뀌지 않는지
6. 생성 성공 시 `llm.last_speculative_stats`를 close 전에 복사하는지
7. grammar 등 미지원 조합에서 명시적 오류가 발생하는지
8. 실행 후 `llm.close()`가 항상 호출되는지

수동 smoke test는 다음 두 가지면 충분하다.

- text: Muse-Glimmer target + DFlash draft, `draft_calls > 0`
- text: compatible MTP target/assistant or embedded NextN target, `draft_calls > 0`

## 현재 검증된 예시 파일

```text
Target:
D:\ComfyUI\models\LLM\Muse-Glimmer\Muse-Glimmer-30B-UD-Q4_K_XL.gguf

Draft:
D:\ComfyUI\models\LLM\Muse-Glimmer\dflash-kquant.gguf
```

이 경로는 검증 환경의 예시이며 노드에 하드코딩하지 않는다. 기존 ComfyUI model selector와
folder registration을 통해 선택하도록 구현한다.
