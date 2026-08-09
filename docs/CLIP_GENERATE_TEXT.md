# ComfyUI CLIP Generate Text 지원 설계

## 결론

`CLIP Generate Text (Image List)`는 ComfyUI 공식 `Generate Text` 노드의 공개 실행 경로를 유지하면서 다음 기능만 추가한다.

1. 별도의 system prompt 입력과 실제 system-role chat template
2. 한 번의 실행에서 IMAGE batch/data list/nested list 처리
3. `auto` 또는 수동 `model_format` 선택

모델을 직접 로드하거나 별도 generation loop를 구현하지 않는다. 로더가 만든 ComfyUI `CLIP` 객체의 `tokenize()`, `generate()`, `decode()`를 그대로 호출하므로 공식 모델 구현의 offload, dtype, generation 및 thinking 동작을 재사용한다. GGUF나 `mmproj`도 이 노드가 로드하지 않는다.

## 공식 Generate Text와의 관계

생성 단계와 sampling 규격은 공식 [`comfy_extras/nodes_textgen.py`](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_textgen.py)를 따른다.

```text
CLIP + prompt + media
  -> clip.tokenize(...)
  -> clip.generate(...)
  -> clip.decode(...)
  -> generated_text
```

추가 계층은 입력 정규화와 chat template 선택뿐이다. 따라서 이 노드는 임의의 conditioning 전용 CLIP을 범용 LLM으로 바꾸지 않는다. 실제로 `generate()`와 `decode()`를 구현한 ComfyUI text-generation 모델만 사용할 수 있다.

## 입력 규격

| 입력 | 의미 |
| --- | --- |
| `clip` | ComfyUI 로더가 반환한 생성 가능한 CLIP |
| `system` | 모델별 실제 system role에 삽입할 문자열 |
| `prompt` | 현재 user turn |
| `images` | IMAGE batch, data list 또는 중첩 list |
| `video` | 공식 노드와 동일한 24 FPS IMAGE frame batch |
| `audio` | 공식 ComfyUI AUDIO |
| `model_format` | `auto`, `qwen3_vl`, `qwen3_5`, `gemma4` |
| `thinking` | 모델이 지원할 때 thinking mode 사용 |
| `use_default_template` | 켜면 모델 template 적용, 끄면 `prompt`를 완성된 raw template로 취급 |

노드는 V3 `is_input_list=True`를 사용한다. 모든 scalar 입력은 정확히 하나의 값이어야 하며, 여러 prompt를 이미지 목록에 자동 매핑하지 않는다. IMAGE 목록만 재귀적으로 펼치고 각 batch 항목을 `[1,H,W,C]`로 분리한다. resize, crop, padding 또는 montage는 하지 않는다.

## system prompt 처리

ComfyUI `CLIP`에는 모든 생성 모델에 공통인 system-message 객체가 없다. 따라서 `system`이 비어 있지 않으면 tokenizer 계열에 맞는 chat template를 전달한다.

- `auto`: tokenizer class/MRO에서 Qwen3-VL, Qwen3.5 또는 Gemma 4를 판별한다.
- 수동 선택: 자동 판별이 불가능하거나 사용자가 명시적으로 고정하려는 경우 사용한다.
- 알 수 없는 tokenizer + 비어 있지 않은 system: 잘못된 특수 토큰을 추측하지 않고 오류를 반환한다.
- 비어 있는 system: 공식 모델 기본 template를 그대로 사용하므로 알 수 없는 생성 모델도 기존 `Generate Text`처럼 동작할 수 있다.
- `use_default_template=false`: `prompt`가 이미 완성된 모델별 template라고 간주하며 별도 `system`은 허용하지 않는다.

Qwen 계열에서는 `<|im_start|>system` turn과 이미지 placeholder를 구성한 `llama_template`를 전달한다. Gemma 4에서는 `<|turn>system` turn, media placeholder 및 thinking channel 시작 규칙을 보존한다. 문자열의 `{`와 `}`는 tokenizer의 `template.format(text)`에 의해 해석되지 않도록 escape한다.

## 모델 및 미디어 지원

| 모델 형식 | IMAGE LIST | 서로 다른 해상도 | VIDEO | AUDIO | system |
| --- | --- | --- | --- | --- | --- |
| Qwen3-VL | 지원 | 지원 | 미지원 | 미지원 | 지원 |
| Qwen3.5 Vision | 지원 | 지원 | 미지원 | 미지원 | 지원 |
| Gemma 4 + `images=` API | 지원 | 지원 | 지원 | 지원¹ | 지원² |
| Gemma 4 구버전 | 동일 해상도만 batch fallback | 미지원 | 지원 | 지원¹ | 지원² |
| 그 외 생성 CLIP | 동일 해상도 batch 또는 단일 IMAGE | 보장하지 않음 | 모델 구현에 위임 | 모델 구현에 위임 | system이 비어 있을 때만 |

1. Gemma 4 AUDIO는 공식 기본 template 경로에서 지원한다.
2. 별도 system과 AUDIO를 동시에 쓰는 경우는 현재 오류로 처리한다. ComfyUI가 audio token 수를 포함하는 공개 system-template formatter를 제공하지 않기 때문이다. system이 비어 있으면 공식 template가 audio placeholder를 정확히 만든다.

Qwen tokenizer는 VIDEO/AUDIO를 소비하지 않으므로 연결 시 조용히 버리지 않고 오류를 반환한다. Gemma 4는 내부적으로 VIDEO를 IMAGE보다 우선하므로 두 입력을 동시에 연결하는 경우도 오류로 명확히 처리한다.

## Gemma 4 PR 연동

[ComfyUI PR #15450](https://github.com/Comfy-Org/ComfyUI/pull/15450)은 Gemma 4 tokenizer에 명시적인 named parameter `images`를 추가한다. 이 노드는 설치된 tokenizer의 `tokenize_with_weights()` 시그니처를 실행 시 검사한다.

- `images`가 명시돼 있으면 각 원본 해상도의 `[1,H,W,C]` 목록을 `clip.tokenize(..., images=[...])`로 전달한다.
- 없으면 같은 해상도끼리만 `torch.cat()`하여 기존 `image=[B,H,W,C]` 경로를 사용한다.
- 구버전에서 서로 다른 해상도가 들어오면 resize하지 않고 PR 링크가 포함된 오류를 반환한다.

따라서 PR 병합을 기다리지 않고 Qwen과 기존 Gemma 기능을 배포할 수 있으며, PR이 포함된 ComfyUI로 업데이트하면 코드 변경 없이 Gemma 4 가변 해상도 LIST 경로가 활성화된다.

## 유지보수 원칙

- ComfyUI 모델의 generation loop를 복제하지 않는다.
- tokenizer family 판별은 class/MRO allowlist로 제한한다.
- 모르는 template를 추측하거나 system을 user prompt 앞에 단순 접두하지 않는다.
- 지원하지 않는 미디어를 조용히 버리지 않는다.
- thinking 출력은 삭제하지 않고 공식 `decode()` 결과를 그대로 반환한다.
- upstream이 공용 system-message/template API를 제공하면 모델별 template builder를 그 API로 교체한다.

## 검증 범위

자동 테스트는 schema 등록, batch/list flatten, Qwen system role과 placeholder 수, Gemma 4 named `images` capability detection, 구버전 이기종 해상도 거부, 공식 default-template passthrough 및 raw-template 검증을 포함한다. 실제 모델 가중치를 사용한 VRAM/offload 및 생성 품질 검증은 ComfyUI 통합 환경에서 별도로 수행한다.
