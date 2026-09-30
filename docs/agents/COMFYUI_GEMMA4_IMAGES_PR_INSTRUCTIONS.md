# ComfyUI Gemma4 가변 해상도 다중 이미지 지원 PR 작업 지시서

이 문서는 별도로 clone한 `Comfy-Org/ComfyUI` 저장소에서 작업할 코딩 에이전트에게 그대로 전달하기 위한 실행 지시서다. 목표는 Gemma4 네이티브 텍스트 인코더가 서로 다른 해상도의 여러 이미지를 한 프롬프트에서 처리하도록 최소 변경을 만들고, 테스트한 뒤 upstream PR을 준비하는 것이다.

## 최종 목표

`comfy/text_encoders/gemma4.py`의 Gemma4 토크나이저가 기존 단일 `image` 텐서뿐 아니라 다음과 같은 이미지 리스트도 처리하게 한다.

```python
clip.tokenize(
    prompt,
    images=[
        torch.Tensor([1, 768, 1024, 3]),
        torch.Tensor([1, 512, 512, 3]),
        torch.Tensor([1, 720, 1280, 3]),
    ],
)
```

각 이미지 또는 이미지 배치는 원본 해상도를 유지한 채 Gemma4의 기존 aspect-ratio-preserving 전처리를 개별 적용받아야 한다. 서로 다른 해상도를 하나의 텐서로 합치기 위해 미리 resize, crop, pad 또는 `torch.cat()`하지 않는다.

## 배경과 근거

- ComfyUI `IMAGE` 배치는 `[B,H,W,C]` 텐서이므로 배치 안의 모든 항목은 같은 `H/W`를 가져야 한다.
- 현재 Gemma4는 단일 `image` 텐서의 배치 차원을 모두 순회하므로 동일 해상도의 다중 이미지는 이미 지원한다.
- 현재 Qwen3.5와 Qwen3-VL 토크나이저는 `images=[Tensor, ...]`와 batched `image` 입력을 모두 처리한다.
- [ComfyUI issue #13927](https://github.com/Comfy-Org/ComfyUI/issues/13927)은 Qwen3.5가 배치 첫 이미지만 사용하던 문제를 다뤘고, [PR #13943](https://github.com/Comfy-Org/ComfyUI/pull/13943)으로 해결됐다. 이 PR의 범위는 가변 해상도 Gemma4 리스트 지원과는 다르다.
- ComfyUI 데이터 리스트는 서로 다른 크기의 이미지를 각각의 값으로 보존할 수 있다. 관련 규격은 [Data lists 문서](https://docs.comfy.org/custom-nodes/backend/lists)를 참고한다.

## 작업 시작 전 필수 절차

1. 사용자의 fork를 만들고 그 fork를 clone한다. 이미 fork/clone이 준비됐다면 다시 만들지 않는다.
2. upstream remote가 `https://github.com/Comfy-Org/ComfyUI.git`을 가리키는지 확인한다.
3. 현재 `master`를 upstream 최신 상태로 맞춘다.
4. 저장소 루트의 `AGENTS.md`, `CONTRIBUTING.md` 및 변경 대상 경로에 추가 지시 파일이 있는지 전부 읽고 따른다.
5. 다음 파일의 현재 구현을 다시 확인한다. 이 문서의 코드 위치나 함수 시그니처가 최신 `master`와 다르면 최신 소스를 기준으로 조정한다.

   - `comfy/text_encoders/gemma4.py`
   - `comfy/text_encoders/qwen35.py`
   - `comfy/text_encoders/qwen3vl.py`
   - `comfy/sd.py`
   - `comfy_extras/nodes_textgen.py`

6. 같은 기능을 구현한 열린 issue나 PR이 새로 생겼는지 GitHub에서 검색한다. 중복 PR이 있으면 구현을 중단하고 사용자에게 보고한다.
7. 깨끗한 `master`에서 `fix/gemma4-multi-resolution-images` 같은 짧은 작업 브랜치를 만든다.

예시 명령은 다음과 같지만, remote 이름과 계정명은 실제 환경에 맞춘다.

```bash
git remote -v
git fetch upstream
git switch master
git merge --ff-only upstream/master
git switch -c fix/gemma4-multi-resolution-images
```

사용자 변경이 있는 dirty worktree를 reset, checkout 또는 삭제하지 않는다. 예상하지 못한 기존 변경이 있으면 멈추고 사용자에게 알린다.

## 구현 범위

우선순위는 Gemma4 모델 통합 경계의 최소 수정이다.

### 필수 변경

`Gemma4_Tokenizer.tokenize_with_weights()`가 다음 입력을 모두 처리하도록 한다.

1. 미디어 없음
2. 기존 `image: Tensor[B,H,W,C]`
3. 새 `images: Sequence[Tensor[B,H,W,C]]`
4. 기존 `video: Tensor[F,H,W,C]`
5. 기존 `audio`

권장 시그니처는 최신 코드 스타일을 따르되, 새 리스트 인자의 기본값으로 mutable list를 사용하지 않는다. 기존 positional caller의 의미를 바꾸지 않도록 `images`는 기존 인자 뒤, `**kwargs` 바로 앞에 추가한다. 현재 제출된 [PR #15450](https://github.com/Comfy-Org/ComfyUI/pull/15450)도 이 형태를 사용한다.

```python
def tokenize_with_weights(
    self,
    text,
    return_word_ids=False,
    image=None,
    audio=None,
    video=None,
    llama_template=None,
    skip_template=True,
    thinking=False,
    images=None,
    **kwargs,
):
```

전처리 순서는 다음 계약을 만족해야 한다.

- `video` 경로는 기존 동작을 보존한다.
- 이미지 경로는 `images`가 제공되면 각 source를 순서대로 처리한다.
- 기존 `image` 입력은 하나의 source로 처리한다.
- 각 source는 자체 `H/W`로 `_get_aspect_ratio_preserving_size()`를 호출한다.
- 각 source의 배치 차원도 전부 순회한다.
- 최종 이미지 순서는 source 순서, 그 안의 batch 순서를 유지한다.
- 이미지 placeholder 수와 생성된 image embed 항목 수가 정확히 일치해야 한다.
- 기존 `max_soft_tokens`, thinking, system/default template, audio 및 decode 동작을 바꾸지 않는다.

구현 형태는 대략 다음과 같아야 하지만 그대로 복사하지 말고 최신 파일의 지역 스타일에 맞춘다.

```python
is_video = video is not None
if is_video:
    sources = [video]
elif images is not None:
    sources = images
elif image is not None:
    sources = [image]
else:
    sources = []

image_pixels = []
for source in sources:
    samples = source.movedim(-1, 1)
    num_frames = samples.shape[0]
    h, w = samples.shape[2], samples.shape[3]
    target_h, target_w = _get_aspect_ratio_preserving_size(...)
    # 기존 픽셀 변환과 image_pixels append를 유지한다.
```

`images=[]` 같은 mutable 기본 인자를 추가하지 않는다. 입력 리스트를 수정하지도 않는다.

### `image`와 `images`의 동시 입력

최신 Qwen 구현과 공유 호출 규격을 조사한 뒤 가장 일관된 규칙을 선택한다. 기본 제안은 다음과 같다.

- `images is not None`이면 명시적인 `images`를 사용한다.
- 그렇지 않으면 기존 `image`를 사용한다.
- 빈 리스트의 의미는 최신 Qwen 규격과 맞춘다. `images=[]`가 기존 `image`로 fallback하는 규격이라면 Gemma4도 동일하게 맞춘다.

동시 입력에 새로운 예외를 추가해 기존 caller를 깨뜨리지 않는다. 선택한 우선순위는 테스트 이름 또는 PR 설명에서 명확하게 드러나야 한다.

### video와 images의 관계

현재 Gemma4는 `video`가 있으면 `image`보다 video를 우선한다. 이 PR에서는 기존 video 우선 동작을 보존한다. 새로운 동시 모달 정책이나 오류 규칙은 별도 논의 없이 추가하지 않는다.

## 기본적으로 수정하지 않을 범위

다음 변경은 이 PR에 포함하지 않는다.

- llama.cpp, GGUF 또는 mmproj 지원
- 새로운 dependency
- Gemma4 모델 구조, vision encoder, projector 또는 generation loop
- `comfy/sd.py`의 광범위한 CLIP API 재설계
- execution list 처리 방식 변경
- 프런트엔드 JavaScript 변경
- 기존 `Generate Text` 노드의 widget/출력 변경
- system prompt나 chat template 기능 추가
- Qwen 코드 리팩터링
- 이미지 자동 resize, crop, pad 또는 강제 batching
- unrelated formatting, rename 또는 cleanup

upstream maintainer가 공식 노드에서 이 기능으로 진입하는 caller도 요구한다면 임의로 범위를 확장하지 않는다. 먼저 현재 V3의 `io.Autogrow` 또는 list input 규격을 조사하고, 별도 커밋이나 후속 PR로 분리할지 사용자 및 reviewer와 합의한다.

## 테스트 요구사항

먼저 기존 Gemma/Qwen tokenizer 테스트가 있는지 검색하고 그 위치와 스타일을 따른다. 없다면 `tests-unit` 아래 가장 가까운 모델 통합 테스트 위치에 작은 회귀 테스트를 추가한다. 테스트만을 위해 큰 helper 계층이나 실제 수 GB 모델 다운로드를 추가하지 않는다.

최소 검증 항목은 다음과 같다.

1. 기존 단일 이미지 입력 결과 구조가 유지된다.
2. 동일 해상도 batched `image`의 모든 항목이 embed로 들어간다.
3. 서로 다른 해상도의 `images` 두 개 이상이 순서대로 처리된다.
4. 리스트의 각 source가 서로 다른 목표 `target_h/target_w`를 계산한다.
5. 하나의 source가 `B>1`일 때 모든 배치 항목이 유지된다.
6. 생성된 이미지 placeholder 수와 embed 수가 일치한다.
7. 이미지가 없을 때 기존 text-only 동작이 유지된다.
8. thinking on/off 템플릿 동작이 변하지 않는다.
9. video가 전달됐을 때 기존 frame subsampling 및 video placeholder 동작이 유지된다.

가능하면 작은 synthetic tensor를 사용한다.

```python
landscape = torch.zeros((1, 384, 640, 3))
square = torch.zeros((1, 512, 512, 3))
portrait_batch = torch.zeros((2, 640, 384, 3))
```

실제 tokenizer JSON 또는 모델 가중치 없이는 완전한 tokenizer 테스트가 불가능하다면 다음 순서로 대응한다.

1. 기존 테스트 fixture나 tokenizer fixture를 재사용한다.
2. 기존 지역 스타일에서 허용하는 최소 monkeypatch로 base tokenization 결과만 대체한다.
3. 그래도 합리적인 단위 테스트가 불가능하면 테스트 전용 production helper를 억지로 만들지 말고, 재현 가능한 수동 검증 스크립트와 결과를 PR에 기록한다.

테스트 명령은 clone한 ComfyUI의 최신 `tests-unit/README.md`, `pyproject.toml` 및 CI 설정을 먼저 확인한 뒤 실행한다. 현재 기본 안내는 다음과 같다.

```bash
python -m pip install -r tests-unit/requirements.txt
python -m pytest tests-unit/
```

전체 테스트 비용이 지나치게 크면 먼저 새 테스트 파일과 인접 테스트를 실행한 뒤 가능한 범위에서 전체 `tests-unit`을 실행한다. 실행하지 못한 검증은 성공한 것처럼 쓰지 말고 이유를 PR에 남긴다.

## 수동 통합 검증

실제 Gemma4 텍스트 인코더가 준비된 환경에서는 다음을 확인한다.

1. 기존 공식 `Generate Text`의 단일 이미지 생성이 회귀하지 않는다.
2. 동일 해상도 이미지 배치가 모두 인식된다.
3. Python 또는 최소 테스트 caller에서 `clip.tokenize(prompt, images=[...])`로 서로 다른 해상도 이미지들을 전달할 수 있다.
4. 생성 결과가 최소한 각 이미지를 구분해 언급할 수 있다.
5. VRAM offload/load 동작과 dtype/device 오류가 새로 생기지 않는다.

수동 검증용 이미지와 모델은 저장소에 커밋하지 않는다.

## 완료 조건

다음 조건을 모두 만족해야 구현 완료로 본다.

- 서로 다른 `H/W`의 이미지 리스트가 resize/pad로 합쳐지지 않고 개별 전처리된다.
- 기존 단일 이미지와 동일 해상도 배치 동작이 유지된다.
- 이미지 순서 및 placeholder 순서가 안정적이다.
- video/audio/thinking/template 동작의 의도하지 않은 변경이 없다.
- 새 dependency가 없다.
- 변경 파일 수와 diff가 작다.
- 관련 테스트가 통과한다.
- `git diff --check`가 통과한다.
- 저장소 `AGENTS.md`의 스타일과 PR 지침을 만족한다.

## 커밋 지침

한 개의 응집된 커밋을 우선한다. 권장 제목은 다음과 같다.

```text
Support multi-resolution images in Gemma4 text generation
```

커밋 전에 다음을 확인한다.

```bash
git status --short
git diff --check
git diff --stat
git diff
```

사용자 승인을 받지 않은 unrelated 파일은 stage하거나 commit하지 않는다.

## PR 제목과 설명 초안

권장 PR 제목:

```text
Support multi-resolution image lists in Gemma4 text generation
```

권장 PR 설명:

```markdown
## Problem

Gemma4 currently accepts a single IMAGE tensor and supports multiple images only when they share one `[B, H, W, C]` shape. Unlike the Qwen text-generation tokenizers, it cannot consume a list of image tensors with independent resolutions.

## Change

- Accept an optional image list in the Gemma4 tokenizer.
- Preprocess each tensor using its own height and width while preserving source and batch order.
- Keep the existing single-image, image-batch, video, audio, template, and thinking paths unchanged.

This does not resize or pad different inputs into a common ComfyUI IMAGE batch.

## Tests

- [실제로 실행한 테스트 명령과 결과만 기재]
- [수동 검증을 했다면 모델/입력 형태와 결과를 간단히 기재]

Related: #13927 and #13943 addressed multi-image batching for Qwen3.5; this PR covers independently sized Gemma4 image inputs.
```

PR 설명은 짧게 유지하고 문제, 변경 동작, 실행한 테스트만 적는다. 구현 일지나 이 문서 전체를 복사하지 않는다.

## PR 제출 전 최종 확인

- 최신 upstream `master`와 충돌 없이 rebase 또는 fast-forward 가능한지 확인한다.
- force push가 필요하면 정확한 본인 작업 브랜치에만 `--force-with-lease`를 사용한다.
- fork의 작업 브랜치로 push한다.
- base는 `Comfy-Org/ComfyUI:master`, head는 사용자 fork의 작업 브랜치로 PR을 연다.
- PR 생성 후 CI 결과와 reviewer 의견을 확인한다.
- reviewer가 범위 축소를 요청하면 우선 따른다.
- 공식 `TextGenerate` UI에 가변 입력 socket을 추가하라는 요청이 나오면 이 PR에 즉시 섞지 말고 별도 범위인지 확인한다.

## 작업 에이전트의 최종 보고 형식

작업을 마친 에이전트는 사용자에게 다음만 간결하게 보고한다.

1. 변경한 동작
2. 변경 파일
3. 실행한 테스트와 결과
4. 커밋 SHA
5. push한 브랜치
6. PR URL과 CI 상태
7. 남은 제한사항 또는 reviewer가 결정해야 할 사항

테스트 실패, upstream 중복 PR, 인증 문제 또는 API 설계상 차단이 있으면 이를 숨기지 말고 정확한 명령과 오류 요약을 보고한다.
