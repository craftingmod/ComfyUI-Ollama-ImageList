# ComfyUI Ollama Image List Nodes 구현 계획

> 이 문서는 초기 설계 기록을 포함한다. 현재 구현과 운영 방법은 [`README.md`](README.md), [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md), [`docs/LLAMA_CPP.md`](docs/LLAMA_CPP.md)를 기준으로 한다.

## 1. 프로젝트 개요

프로젝트명은 `ComfyUI-Ollama-ImageList`로 한다. 이 프로젝트는 ComfyUI의 이미지 배치와 data list를 혼동하지 않고, 서로 다른 해상도의 이미지 여러 장을 하나의 Ollama 요청으로 전달하는 데 목적이 있다.

1차 백엔드는 Ollama REST API이며, 2차 백엔드로 `llama-cpp-python` 네이티브 실행을 선택적으로 제공할 수 있도록 코어와 백엔드 계층을 분리한다.

핵심 사용 사례는 다음과 같다.

```text
system prompt + user prompt
        +
IMAGE single / batch / list / data list
        +
AUDIO single / batch / list / data list
        ↓
정규화된 독립 미디어 항목 목록
        ↓
Ollama 또는 llama-cpp-python 단일 요청
        ↓
response / thinking / metrics / debug manifest
```

이 문서는 별도 저장소를 생성하여 구현할 때 사용할 설계 및 작업 계획이다. 현재 저장소의 워크플로우나 프롬프트 파일을 직접 변경하는 계획은 포함하지 않는다.

## 2. 목표

### 필수 목표

- 사용자가 `system`과 `prompt`를 완전히 직접 입력할 수 있어야 한다.
- 다음 이미지 입력을 동일한 노드에서 모두 처리해야 한다.
  - 단일 IMAGE 텐서
  - 동일 해상도 IMAGE batch
  - 서로 다른 해상도의 IMAGE list
  - `Create List` 등에서 생성된 ComfyUI data list
  - list 안에 batch가 포함된 혼합 형태
- data list를 항목별 노드 실행으로 매핑하지 않고, 전체 목록을 한 번에 받아 LLM 요청을 정확히 한 번만 실행해야 한다.
- 각 이미지는 원래 H×W와 순서를 유지해야 한다.
- 기본 동작에서는 resize, crop, letterbox, 투명 패딩을 하지 않아야 한다.
- 각 이미지를 독립 PNG로 인코딩해 멀티모달 요청의 미디어 배열에 넣어야 한다.
- ComfyUI `AUDIO` 입력을 받을 수 있는 공통 미디어 구조를 마련해야 한다.
- Ollama의 응답 본문, thinking, 사용량/시간 정보, 디버그 정보를 별도 출력해야 한다.
- 기본 Ollama 구현에는 무거운 Python 의존성을 추가하지 않아야 한다.
- 오류가 발생하면 자동으로 이미지별 다중 호출로 의미를 바꾸지 말고 명확히 실패해야 한다.

### 권장 목표

- Ollama `/api/chat` 기반의 stateless 요청을 기본으로 한다.
- JSON 또는 JSON Schema 형식 출력을 지원한다.
- `temperature`, `top_p`, `top_k`, `min_p`, `seed`, `num_ctx`, `num_predict`, `repeat_penalty`, `stop`, `keep_alive`, `think`를 설정할 수 있게 한다.
- 요청 전에 선택적으로 Ollama 연결, 버전, 모델 존재 여부를 검사한다.
- base64 본문을 제외한 안전한 request manifest를 출력한다.
- 동일한 미디어 정규화 코어를 Ollama와 `llama-cpp-python`이 공유한다.

## 3. 비목표

첫 릴리스에서는 다음을 구현하지 않는다.

- Ollama 모델 설치, 삭제, pull 또는 Modelfile 관리
- 영구적인 대화 세션과 이미지 임베딩 캐시
- deprecated된 Ollama `context` 토큰 배열에 이미지 정보를 저장하는 기능
- 이미지별 호출 결과를 합치는 자동 fallback
- 모델이 지원하지 않는 다중 이미지를 임의 montage로 합치는 fallback
- 비디오 전체 디코딩 및 프레임 샘플링
- 이미지 생성 모델 지원
- llama.cpp의 모든 모델별 chat handler 자동 호환
- 실시간 음성 대화 또는 오디오 출력

이 기능들은 코어가 안정화된 뒤 별도 마일스톤으로 검토한다.

## 4. 핵심 설계 결정

### 4.1 ComfyUI data list를 실행 단위가 아닌 데이터로 수신

ComfyUI는 기본적으로 data list를 받으면 노드를 항목별로 반복 실행한다. 이를 막기 위해 멀티모달 노드는 `INPUT_IS_LIST = True`를 사용한다.

`INPUT_IS_LIST`는 노드 전체에 적용되므로 이미지뿐 아니라 `system`, `prompt`, `model`, 숫자 옵션 등도 모두 리스트로 전달된다. 따라서 노드 함수에 직접 비즈니스 로직을 넣지 않고 다음 정규화 함수를 먼저 통과시킨다.

```text
unwrap_required_scalar(name, values)
unwrap_optional_scalar(name, values, default)
flatten_image_inputs(values)
flatten_audio_inputs(values)
```

스칼라 입력은 길이 1만 허용하는 것을 기본으로 한다. 동일 노드에 여러 system 또는 prompt가 data list로 들어오면 마지막 값을 암묵적으로 선택하지 않고 오류를 낸다.

ComfyUI의 list 처리 사양은 공식 [Data lists 문서](https://docs.comfy.org/custom-nodes/backend/lists)를 기준으로 한다.

### 4.2 이미지 입력 정규화

정규화 결과는 다음 내부 자료형으로 통일한다.

```python
@dataclass(frozen=True)
class MediaItem:
    kind: Literal["image", "audio"]
    index: int
    mime_type: str
    payload: bytes
    metadata: dict[str, Any]
```

이미지 입력 규칙은 다음과 같다.

- 3차원 텐서 `[H, W, C]`는 이미지 1장으로 취급한다.
- 4차원 텐서 `[B, H, W, C]`는 batch 차원을 따라 B장으로 분리한다.
- list 또는 중첩 list는 재귀적으로 평탄화한다.
- list 안의 각 batch도 다시 개별 이미지로 분리한다.
- 입력 목록 순서와 batch 내부 순서를 안정적으로 유지한다.
- 채널 수는 1, 3, 4를 허용하고 그 외에는 명확히 실패한다.
- RGB/RGBA 텐서는 기본적으로 PNG로 무손실 인코딩한다.
- RGBA가 실제로 입력된 경우에는 알파를 보존하되, 표준 ComfyUI `Load Image`가 알파를 MASK로 분리할 수 있다는 점을 문서화한다.
- 크기 변경, 패딩, 색상 배경 합성을 하지 않는다.
- EXIF와 원본 파일 메타데이터는 ComfyUI 텐서 단계에서 이미 사라질 수 있으므로 보존을 약속하지 않는다.

`flatten_image_inputs()`는 최소한 다음 형태를 모두 동일하게 처리해야 한다.

```text
Tensor[1,H,W,C]
Tensor[B,H,W,C]
[Tensor[1,H1,W1,C], Tensor[1,H2,W2,C]]
[Tensor[B1,H1,W1,C], Tensor[B2,H2,W2,C]]
[[Tensor[...]], Tensor[...]]
```

### 4.3 Ollama는 `/api/chat` 사용

Ollama 백엔드는 기본적으로 다음 요청을 생성한다.

```json
{
  "model": "model-name",
  "messages": [
    {
      "role": "system",
      "content": "user supplied system prompt"
    },
    {
      "role": "user",
      "content": "user supplied prompt",
      "images": [
        "<base64 png 1>",
        "<base64 png 2>"
      ]
    }
  ],
  "stream": false,
  "think": false,
  "format": "",
  "options": {},
  "keep_alive": "5m"
}
```

Ollama 공식 Vision API는 REST 요청에서 `images`를 Base64 문자열 배열로 받는다. 각 배열 원소는 독립 이미지이므로 크기를 동일하게 만들 필요가 없다. 구현 기준은 [Ollama Vision 문서](https://docs.ollama.com/capabilities/vision)와 [Chat API 문서](https://docs.ollama.com/api/chat)로 한다.

`/api/generate`가 아니라 `/api/chat`을 선택하는 이유는 다음과 같다.

- system과 user 역할이 명확하다.
- 이미지가 현재 user message에 속한다는 구조가 명확하다.
- deprecated된 `context` 필드에 의존하지 않는다.
- 향후 명시적 history 입력을 추가하기 쉽다.

첫 릴리스는 `stream=false`만 지원한다. ComfyUI 실행 중 부분 응답 UI를 안정적으로 갱신하는 기능은 별도 단계로 둔다.

### 4.4 Ollama 오디오 지원 정책

현재 Ollama 공식 `GenerateRequest`와 `Message` 공개 스키마에는 독립적인 `audio` 필드가 없고, 문서화된 멀티모달 입력은 `images` 배열이다. 따라서 오디오를 이미지와 같은 안정 지원 기능으로 표시해서는 안 된다.

노드 인터페이스와 코어는 ComfyUI AUDIO를 다음과 같이 정상화한다.

- waveform과 sample rate 검증
- batch, channel, sample 차원 검증
- 필요 시 batch별 오디오 항목 분리
- float waveform을 PCM16 WAV bytes로 변환
- 선택적으로 mono downmix
- 선택적으로 16 kHz resample
- 원래 길이, sample rate, channel 수를 metadata에 기록

Ollama 전송은 다음 전략으로 분리한다.

```text
audio_transport = disabled
  공식 지원 전까지 기본값. AUDIO가 들어오면 설명 가능한 오류 반환.

audio_transport = experimental_wav_in_images
  WAV bytes를 images 배열에 넣는 비공식 호환 경로.
  명시적으로 opt-in한 경우에만 사용.

audio_transport = native
  향후 Ollama 공식 API에 audio 필드가 추가되면 버전/기능 탐지 후 사용.
```

실험적 모드는 모델과 Ollama 버전에 따라 작동하지 않거나 품질이 낮을 수 있다. 자동으로 켜지 않으며 README와 노드 tooltip에 비공식 기능임을 명시한다.

### 4.5 전송 의존성 최소화

Ollama REST 클라이언트는 우선 Python 표준 라이브러리 또는 ComfyUI에 이미 포함된 HTTP 계층을 사용한다. 공식 `ollama` Python SDK를 필수 의존성으로 추가하지 않는다.

필수 동작은 다음으로 제한한다.

- JSON 직렬화
- Base64 인코딩
- HTTP POST와 timeout
- HTTP 상태 코드 및 Ollama 오류 본문 처리
- 응답 JSON 파싱

Base64 이미지 본문은 로그, raw manifest, 예외 메시지에 출력하지 않는다.

## 5. 제공 노드 설계

### 5.1 `Ollama Generate (Image List)`

MVP의 핵심 stateless 노드다.

필수 입력:

| 입력 | 타입 | 설명 |
|---|---|---|
| `url` | STRING | 기본값 `http://127.0.0.1:11434` |
| `model` | STRING | Ollama 모델명 |
| `system` | STRING multiline | 사용자 정의 system prompt |
| `prompt` | STRING multiline | 사용자 정의 user prompt |

선택 입력:

| 입력 | 타입 | 설명 |
|---|---|---|
| `images` | IMAGE 또는 flexible input | single/batch/list/data list |
| `options_json` | STRING multiline | Ollama options object |
| `format_json` | STRING multiline | 빈 문자열, `json`, 또는 JSON Schema |
| `think` | enum | `off/on/low/medium/high/max` |
| `keep_alive` | STRING | 예: `5m`, `0`, `-1` |
| `timeout_seconds` | INT | 연결 및 요청 제한 시간 |
| `debug` | BOOLEAN | payload를 제외한 진단 정보 출력 |

출력:

| 출력 | 타입 | 설명 |
|---|---|---|
| `response` | STRING | 최종 답변 |
| `thinking` | STRING | 지원 모델의 thinking 출력 |
| `raw_json` | STRING | Base64를 포함하지 않는 응답 JSON |
| `metrics_json` | STRING | durations와 token counts |
| `image_manifest_json` | STRING | 이미지 순서, 크기, MIME, byte 크기 |

### 5.2 `Ollama Image List Media Bundle`

현재 공개 확장 등록에서는 비활성화한다. 내부 구현은 향후 명시적인 opt-in 기능을 검토할 수 있도록 유지한다. 활성화할 경우 동일한 list-aware 정규화 기능을 사용하여 opaque 타입 `OLLAMA_IMAGE_LIST_MEDIA`를 출력한다.

용도:

- 여러 subgraph에서 같은 미디어 목록 재사용
- LLM 노드 실행 전에 실제 이미지 순서와 크기 확인
- 향후 Ollama와 llama.cpp 노드가 같은 입력 묶음 사용

Bundle에는 raw tensor를 유지할지 즉시 bytes로 인코딩할지 선택할 수 있지만, MVP에서는 실행 시점 메모리 사용과 직렬화 안정성을 위해 bytes 기반 immutable bundle을 우선한다. ComfyUI workflow JSON에는 payload 자체를 저장하지 않는다.

### 5.3 `Llama.cpp Generate (Multimodal)` (선택 기능)

Ollama와 독립된 선택적 네이티브 실행 노드로 구현되었다. 주요 입력은 다음과 같다.

- `model_path`
- `mmproj_path`
- handler 선택과 `thinking`
- `n_ctx`
- `max_tokens`
- `gpu_layers`
- `main_gpu`
- `n_batch`, 선택적 `n_ubatch`, 선택적 `image_max_tokens`
- `flash_attention`, `use_mmap`, `verbose`
- IMAGE, AUDIO, VIDEO list 입력
- typed sampling 및 Gemma 4 runtime preset 입력

### 5.4 네이티브 모델 언로드 정책

별도 Unload 노드는 제공하지 않는다. Generate가 모델 출력이나 캐시를 유지하지 않고, 성공과 실패 모두에서 한 번의 completion 직후 모델과 handler를 닫는다.

## 6. `llama-cpp-python` 네이티브 구현 가능성

### 결론

이미지, 오디오, 비디오 입력 경로가 구현되었다. 실제 지원 여부는 설치한 fork build, 모델, mmproj, MTMD handler와 template에 강하게 의존한다.

공식 `llama-cpp-python`은 모델별 chat handler와 OpenAI 스타일 `image_url` content part를 이용한 Vision API를 제공하며, local image를 Base64 data URI로 전달할 수 있다. 기준 자료는 [`llama-cpp-python` multimodal 문서](https://github.com/abetlen/llama-cpp-python#multi-modal-models)로 한다.

이미지 구현 흐름은 다음과 같다.

```text
MediaItem(image/png bytes)
  → data:image/png;base64,...
  → user content의 복수 image_url part
  → llm.create_chat_completion(...)
```

다만 실제 복수 이미지 지원 여부는 선택한 모델과 chat handler에 따라 다르다. 따라서 모델별 capability matrix와 통합 테스트가 필요하다.

### 네이티브 구현의 장점

- Ollama가 지원하지 않는 최신 handler나 fork 기능을 직접 선택할 수 있다.
- 모델 로딩, KV cache, GPU layer, tensor split을 세밀하게 제어할 수 있다.
- 공통 `MediaItem` 목록을 이용하므로 서로 다른 이미지 해상도를 그대로 보존할 수 있다.
- 별도 Ollama 서버가 필요 없다.

### 네이티브 구현의 위험과 비용

- `llama-cpp-python`은 플랫폼과 CUDA/ROCm/Metal 버전에 맞는 wheel 또는 로컬 빌드가 필요하다.
- ComfyUI가 사용하는 Torch/CUDA 환경과 별도로 native backend 호환성을 관리해야 한다.
- 모델별 mmproj와 chat handler 선택이 필요하다.
- 일부 최신 Vision/Audio 모델은 공식 PyPI build보다 특정 fork가 먼저 지원할 수 있다.
- native crash나 OOM이 ComfyUI 프로세스 전체에 영향을 줄 수 있다.
- 모델 unload, VRAM 회수, 동시 실행 잠금까지 구현 범위가 넓어진다.

### 권장 배포 방식

- 기본 설치에는 `llama-cpp-python`을 포함하지 않는다.
- import가 실패하면 ComfyUI 시작 자체를 막지 않고 native 노드만 설명 가능한 오류를 표시한다.
- generic MTMD와 audio/video 기능을 제공하는 호환 fork wheel은 사용자가 ComfyUI Python 환경에 직접 설치한다.
- wheel 선택과 모델 호환성은 [`docs/LLAMA_CPP.md`](docs/LLAMA_CPP.md)에 문서화한다.

## 7. 제안 디렉터리 구조

```text
ComfyUI-Ollama-ImageList/
├─ __init__.py
├─ pyproject.toml
├─ requirements.txt
├─ README.md
├─ LICENSE
├─ CHANGELOG.md
├─ nodes/
│  ├─ __init__.py
│  ├─ ollama_generate.py
│  ├─ media_bundle.py
│  └─ llama_cpp_generate.py
├─ core/
│  ├─ media_types.py
│  ├─ normalize_inputs.py
│  ├─ encode_image.py
│  ├─ encode_audio.py
│  ├─ errors.py
│  └─ capabilities.py
├─ backends/
│  ├─ base.py
│  ├─ ollama_rest.py
│  └─ llama_cpp_native.py
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ fixtures/
├─ examples/
│  ├─ single_image.json
│  ├─ same_size_batch.json
│  ├─ heterogeneous_data_list.json
│  ├─ list_of_batches.json
│  └─ audio_experimental.json
└─ docs/
   ├─ INPUT_SEMANTICS.md
   ├─ OLLAMA.md
   ├─ AUDIO.md
   ├─ LLAMA_CPP.md
   └─ COMPATIBILITY.md
```

GPL 프로젝트의 구현 코드를 복사하지 않고 공개 API와 동작을 기준으로 독립 구현한다. 프로젝트 라이선스는 의존성과 배포 정책을 검토한 뒤 MIT 또는 Apache-2.0 중 하나를 선택한다.

## 8. 단계별 구현 계획

### Phase 0 — 저장소 스캐폴딩

- 새 Git 저장소 생성
- `pyproject.toml`, 패키지 메타데이터, 라이선스, 기본 README 작성
- ComfyUI가 노드를 발견할 수 있도록 `NODE_CLASS_MAPPINGS`와 표시 이름 등록
- lint, formatting, pytest 설정
- Windows/Linux CI 추가

완료 조건:

- ComfyUI 시작 시 노드가 로드된다.
- Ollama나 llama-cpp-python이 설치되지 않아도 플러그인 import가 실패하지 않는다.

### Phase 1 — 미디어 정규화 코어

- `INPUT_IS_LIST=True` 기반 입력 수신 구현
- scalar unwrapping 구현
- image tensor single/batch/list/data list 평탄화 구현
- 중첩 list와 list-of-batches 지원
- PNG 인코딩과 manifest 생성
- AUDIO 검증 및 WAV PCM16 인코딩 구현
- 입력 수, pixel 수, encoded byte 제한 구현

완료 조건:

- 네트워크 없이 모든 입력 조합을 unit test로 검증한다.
- 서로 다른 H×W가 변경되지 않는다.
- 정규화 순서가 항상 결정적이다.

### Phase 2 — Ollama 이미지 MVP

- `/api/chat` request builder 구현
- system, prompt, images 배열 전달
- options, format, think, keep_alive 처리
- timeout과 HTTP/Ollama 오류 처리
- response, thinking, metrics 파싱
- payload를 노출하지 않는 debug manifest 구현
- mock Ollama server integration test 구현

완료 조건:

- single image 요청 1회
- 동일 해상도 batch 요청 1회, images 길이 B
- 서로 다른 해상도 data list 요청 1회, images 길이 N
- list-of-batches 요청 1회, flatten된 전체 images 길이 일치
- 각 Base64 PNG를 디코딩했을 때 원래 H×W와 순서가 일치
- system과 prompt가 바이트 수준으로 의도치 않게 수정되지 않음

### Phase 3 — 실제 Ollama 호환성 검증

- `/api/version`, `/api/tags`, `/api/show` 선택 검사 구현
- 최소 2개 Vision 모델로 단일/복수 이미지 검증
- 다중 이미지를 지원하지 않는 모델의 오류 보존
- 큰 이미지, 긴 prompt, timeout, OOM 오류 메시지 정리
- example workflow 작성

완료 조건:

- Create List에 서로 다른 해상도 2장 이상을 연결했을 때 Ollama 요청 로그가 한 번만 기록된다.
- 모델이 모든 이미지를 구분하도록 이미지 순서를 포함한 검증 prompt로 수동 QA를 통과한다.

### Phase 4 — 오디오 실험 지원

- ComfyUI AUDIO single/batch/list 정규화 테스트
- PCM16 WAV 변환, mono downmix, 16 kHz resample 구현
- `experimental_wav_in_images` 전송 구현
- 모델/버전 allowlist가 아니라 명시적 사용자 opt-in 적용
- 실패 시 이미지 또는 텍스트로 fallback하지 않고 명시적 오류 반환
- 호환성 결과를 모델, Ollama 버전, OS, backend별로 기록

완료 조건:

- `audio_transport=disabled`에서 AUDIO 입력 시 의도된 오류가 발생한다.
- 실험 모드에서 전송된 bytes가 올바른 RIFF/WAVE 파일이다.
- 지원 확인 모델에서 최소 한 번의 audio-to-text 응답을 통합 테스트한다.

### Phase 5 — llama-cpp-python 멀티모달 실행

- optional dependency와 lazy import 구현
- GGUF, mmproj, chat handler 로딩 구현
- 공통 MediaItem을 복수 `image_url` content part로 변환
- system/prompt와 generation options 전달
- 모델 인스턴스 실행 잠금과 completion 직후 무조건 cleanup 구현
- sampling/runtime preset과 MTMD diagnostics 구현

완료 조건:

- 지원 모델 하나에서 서로 다른 크기의 이미지 2장을 한 번의 native 호출로 처리한다.
- Ollama backend와 동일한 입력 workflow를 media bundle 교체 없이 사용할 수 있다.
- llama-cpp-python이 없는 환경에서도 Ollama 노드는 정상 작동한다.

### Phase 6 — llama.cpp 오디오·비디오 및 확장 기능 검토

- 공식 build와 선택 fork의 audio content part/MTMD 지원 조사
- 지원 handler에 한해서 `input_audio` 또는 해당 native API adapter 구현
- ComfyUI VIDEO 원본 stream을 fork의 internal `video` content part로 전달
- capability matrix 작성
- native crash 격리가 필요하면 subprocess worker 설계
- streaming, explicit history, structured output 개선 검토

오디오와 비디오 전송 경로는 구현되었지만 호환성은 model/mmproj/template/build 조합별로 검증한다.

## 9. 테스트 매트릭스

| 사례 | 입력 | 기대 요청 횟수 | 기대 미디어 수 | 크기 보존 |
|---|---:|---:|---:|---|
| single | `[1,H,W,C]` | 1 | 1 | 예 |
| batch | `[B,H,W,C]` | 1 | B | 예 |
| data list | H×W가 다른 텐서 N개 | 1 | N | 예 |
| list of batches | 서로 다른 H×W batch 여러 개 | 1 | 모든 B의 합 | 예 |
| empty | 미디어 없음 | 1 | 0 | 해당 없음 |
| nested empty | 빈 list 포함 | 1 | 유효 항목만 | 예 |
| invalid channel | C=2 또는 C>4 | 0 | 0 | 오류 |
| oversized | 제한 초과 | 0 | 0 | 오류 |
| mixed image/audio | image N + audio M | backend별 | N+M | 정책별 |

추가 검증 항목:

- RGB, grayscale, RGBA
- float 값 clipping과 NaN/Inf 처리
- batch 크기 1과 2 이상
- 매우 다른 portrait/landscape 조합
- Unicode system/prompt
- JSON Schema format
- `think` 지원/미지원 모델
- HTTP 400/404/500, 연결 거부, timeout, 잘못된 JSON
- Base64 또는 사용자 prompt가 로그에 노출되지 않는지 확인
- 같은 입력에서 manifest 순서와 해시가 재현되는지 확인

## 10. 성능 및 안전 제한

기본 제한값은 설정 가능하게 두되 다음 방어가 필요하다.

- 최대 이미지 수
- 이미지당 최대 pixel 수
- 전체 raw tensor 추정 byte 수
- 전체 인코딩 payload byte 수
- 최대 오디오 길이
- 최대 요청 시간
- 재귀 list 최대 깊이

PNG의 투명/단색 영역은 압축이 잘되더라도 Base64 변환 시 약 33%의 전송 크기 증가가 생긴다. 노드는 padding으로 pixel 수를 늘리지 않으며, request manifest에 각 encoded byte 크기와 총합을 제공한다.

서버 URL은 사용자가 지정할 수 있지만 다음을 적용한다.

- 기본값은 loopback 주소
- `http`와 `https`만 허용
- URL에 포함된 credential을 로그에 출력하지 않음
- 임의 이미지 URL을 서버 측에서 다운로드하지 않음
- 인증이 필요하면 raw token 입력 대신 환경변수 이름을 참조하는 방식을 우선 검토

## 11. 오류 처리 원칙

- 입력 정규화 오류와 backend 오류를 구분한다.
- 오류 메시지에는 어떤 입력 index가 실패했는지 포함한다.
- 모델이 여러 이미지를 지원하지 않으면 서버 오류를 그대로 요약해 전달한다.
- audio가 미지원이면 해당 모델이 이미지를 지원한다는 이유로 성공 처리하지 않는다.
- context 길이 초과 시 이미지를 임의 제거하지 않는다.
- OOM 시 이미지 resize나 batch 분할을 자동 수행하지 않는다.
- 자동 fallback은 시각적 의미와 호출 횟수를 바꾸므로 기본적으로 금지한다.

## 12. 문서화 요구사항

README에는 다음을 반드시 포함한다.

- batch와 data list의 차이
- 서로 다른 해상도가 보존되는 이유
- 요청이 한 번만 실행되는지 확인하는 방법
- Ollama 모델별 다중 이미지 지원 차이
- system/prompt가 전달되는 정확한 위치
- 이미지가 history/context에 자동 보존되지 않는다는 설명
- 오디오 기능의 실험 상태
- llama-cpp-python optional dependency 설치 방법과 위험
- Windows CUDA, Linux CUDA, CPU 설치 예시
- 개인정보가 포함된 이미지가 remote Ollama URL로 전송될 수 있다는 경고

example workflow에는 최소 다음 5개를 포함한다.

1. 단일 이미지
2. 동일 해상도 batch
3. 서로 다른 해상도 Create List
4. list of batches
5. 실험적 AUDIO

## 13. 릴리스 기준

### v0.1.0

- Ollama stateless `/api/chat`
- system/prompt 사용자 입력
- image single/batch/list/data list
- 원본 H×W 보존
- non-streaming response/thinking/metrics
- unit test와 mock integration test

### v0.2.0

- optional JamePeng `llama-cpp-python` native backend
- IMAGE, AUDIO, VIDEO list 입력을 한 completion으로 처리
- sampling preset과 Gemma 4 runtime preset
- thinking 제어와 response/thinking 분리
- MTMD capability/evaluated-count diagnostics
- 요청 단위 즉시 unload와 native 실행 직렬화

### v0.3.0 이후 검토

- 실제 모델 및 운영체제별 compatibility matrix 확대
- optional Media Bundle 노드
- JSON Schema와 structured output 개선
- streaming, explicit history, subprocess 격리 검토

### v1.0.0

- 최소 2개 Ollama Vision 모델과 1개 llama.cpp Vision 구성 검증
- ComfyUI 지원 버전 명시
- API/노드 이름 안정화
- 마이그레이션 정책과 changelog 확립
- audio는 검증 수준에 따라 stable 또는 experimental로 별도 표시

## 14. 구현 전 최종 결정 사항

구현 시작 시 다음 기본값을 확정한다.

- 최종 프로젝트명과 Python package명
- 최소 지원 ComfyUI 버전
- classic node API와 V3 node API 중 초기 대상
- 기본 최대 이미지 수와 payload 크기
- 인증 지원 범위
- Ollama Cloud 지원 여부
- official llama-cpp-python만 지원할지 특정 fork를 별도 extra로 둘지 여부

권장 초기 결정은 다음과 같다.

```text
프로젝트명: ComfyUI-Ollama-ImageList
백엔드 우선순위: Ollama REST → llama-cpp-python optional
ComfyUI list 처리: INPUT_IS_LIST=True
Ollama endpoint: /api/chat
이미지 형식: PNG
자동 resize/padding: 없음
streaming: v0.1에서는 없음
audio: experimental opt-in
llama-cpp-python: 기본 requirements에서 제외
세션/history: v0.1에서는 없음
```

이 범위로 시작하면 가장 중요한 문제인 “서로 다른 해상도의 이미지 data list를 한 번의 멀티모달 요청으로 전달”을 먼저 해결하면서, Ollama와 native llama.cpp의 의존성 및 호환성 위험을 서로 격리할 수 있다.
