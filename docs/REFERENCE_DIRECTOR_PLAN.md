# Reference Director 설계 계획

## 문서 상태

- 상태: 설계 단계
- 대상: 단일 ComfyUI V3 커스텀 노드와 그 프론트엔드 확장
- 우선 대상 UI: Nodes 2.0
- 호환 대상 UI: Legacy Canvas
- 핵심 전제: 타임라인 동기화 기능은 구현하지 않는다.

이 문서는 이미지, 오디오, 비디오 reference를 한 노드에서 정렬하고 설명을 붙이고 비파괴 편집한 뒤, 미디어 종류별 독립 리스트와 대응하는 문자열 리스트로 출력하는 `Reference Director`의 현재 설계를 정리한다.

## 결정 요약

| 항목 | 현재 결정 | 상태 |
| --- | --- | --- |
| 미디어 시간축 | 미디어 사이의 타임라인 동기화 없음 | 합의됨 |
| 이미지 출력 | 서로 다른 해상도를 유지하는 `list<IMAGE>` | 합의됨 |
| 오디오 출력 | 서로 다른 길이를 유지하는 `list<AUDIO>` | 합의됨 |
| 비디오 출력 | 서로 다른 크기와 길이를 유지하는 `list<VIDEO>` | 합의 방향 |
| Tensor batch | 공통 크기로 resize/padding한 batch를 만들지 않음 | 합의됨 |
| 캡션 출력 | 미디어 리스트와 동일한 인덱스의 `list<STRING>` | 합의됨 |
| 추가 출력 | 투명하게 검사 가능한 scalar `manifest_json` | 합의됨 |
| 전체 시각 순서 | 이미지와 비디오가 섞인 순서를 manifest에 별도 보존 | 권장안 |
| 비디오 오디오 | 비디오 출력에서는 제거하고 필요할 때 별도 AUDIO로 추출 | 미결정 |
| 카드 비율 | UI 표시 전용 고정 비율; 출력 크기에 영향 없음 | 합의됨 |
| 미리보기 | 노드에서 조절 가능한 최대 픽셀 수의 WebP proxy | 합의됨 |
| 편집 | 원본을 덮어쓰지 않는 recipe와 sidecar 방식 | 권장안 |
| 메인 렌더링 | DOM + CSS Grid/Flex | 합의 방향 |
| Canvas | 이미지 편집, waveform 등 국소 영역에만 사용 | 합의 방향 |
| 프론트엔드 | Vite + strict TypeScript 재도입 | 권장안 |
| UI 프레임워크 | 우선 vanilla TypeScript; 필요 시 격리된 React/Preact root | 미결정 |
| LLM 처리 | Director 밖의 Analyzer/Prompt Composer가 담당 | 권장안 |

## 목표

1. 한 노드에서 여러 이미지, 오디오, 비디오를 편리하게 추가하고 제거한다.
2. 모든 미디어 카드가 같은 표시 비율을 갖되 원본 미디어 규격은 변경하지 않는다.
3. 시각 채널과 오디오 채널을 분리해 V/A 포함 여부를 명확히 표시한다.
4. 드래그 앤 드롭으로 reference 순서를 변경한다.
5. 모든 미디어에 사용자가 작성한 캡션을 붙인다.
6. 큰 원본 대신 가벼운 proxy와 waveform으로 노드 UI를 빠르게 유지한다.
7. 더블클릭 편집기를 제공하고 Undo/Redo를 지원한다.
8. 출력 데이터와 순서, 편집 상태를 opaque custom guide 없이 검사할 수 있게 한다.
9. Nodes 2.0을 주 UI로 사용하면서 합리적인 범위에서 Legacy Canvas도 지원한다.

## 범위 밖

- 여러 미디어의 시작 시각을 맞추는 타임라인
- Premiere Pro와 같은 다중 트랙 편집기
- 영상 프레임 단위 편집
- 오디오 믹싱, crossfade, loudness mastering
- 서로 다른 이미지를 공통 해상도로 맞춘 tensor batch
- Director 내부에서 LLM/VLM 모델을 로드하고 최종 프롬프트를 생성하는 기능
- workflow JSON 안에 원본 미디어, WebP 또는 waveform을 base64로 저장하는 기능

## 핵심 불변 조건

다음 조건은 구현과 테스트에서 항상 유지한다.

1. `card_aspect_ratio`는 CSS 표시 전용이다.
2. `preview_max_pixels`는 proxy 생성에만 영향을 주며 실행 출력에는 영향을 주지 않는다.
3. 사용자가 명시적으로 적용한 crop이나 mask 편집만 출력 미디어를 변경한다.
4. 각 이미지의 해상도는 독립적이다.
5. 각 오디오의 길이와 sample rate 정보는 독립적이다.
6. 각 비디오의 해상도, 길이, frame rate 정보는 독립적이다.
7. 미디어와 캡션 리스트의 길이와 인덱스는 항상 일치한다.
8. 비활성화된 항목은 실제 미디어 리스트에서는 제외하지만 manifest에는 남긴다.
9. manifest에는 tensor, decoded audio, video frame 또는 base64 blob을 넣지 않는다.
10. 원본 입력 파일을 편집 결과로 덮어쓰지 않는다.

## 노드 출력 계약

권장 출력 순서는 다음과 같다.

```text
images          : list<IMAGE>
image_captions  : list<STRING>

audios          : list<AUDIO>
audio_captions  : list<STRING>

videos          : list<VIDEO>
video_captions  : list<STRING>

manifest_json   : STRING
```

ComfyUI V3 출력에서 미디어와 캡션 socket은 list output으로 선언한다. 구현 시점의 공식 ComfyUI `VIDEO` 데이터 계약은 다시 확인한다.

### 인덱스 규칙

```text
images[i]  <-> image_captions[i] <-> manifest.outputs.images[i]
audios[i]  <-> audio_captions[i] <-> manifest.outputs.audios[i]
videos[i]  <-> video_captions[i] <-> manifest.outputs.videos[i]
```

- 캡션이 없는 항목은 생략하지 않고 빈 문자열 `""`을 출력한다.
- `None` placeholder를 넣지 않는다.
- Ignore된 항목을 출력 리스트에서 제거한 다음 남은 항목끼리 다시 연속 인덱스를 갖는다.
- 이미지와 비디오가 섞인 전체 시각 순서는 `manifest.visual_order`로 복원한다.
- `manifest.outputs`는 실제 출력 리스트의 stable item ID 순서를 기록한다.

### IMAGE 규칙

- 각 IMAGE 항목은 독립적인 `[1, H, W, C]` tensor다.
- 서로 다른 항목을 `torch.cat`하지 않는다.
- 공통 resize, padding, letterbox 또는 montage를 자동 적용하지 않는다.
- 명시적으로 적용된 편집 결과만 tensor에 반영한다.

### AUDIO 규칙

- 각 AUDIO 항목은 별도 ComfyUI AUDIO 객체다.
- crop이 적용되면 해당 항목만 변경한다.
- waveform proxy는 출력 AUDIO 데이터가 아니다.

### VIDEO 규칙

- VIDEO를 IMAGE frame batch로 변환하지 않는다.
- V 활성화 여부와 A 활성화 여부를 독립적으로 관리한다.
- 비디오 내장 오디오 정책은 구현 전에 아래 대안 중 하나로 확정한다.

| V | A | 권장 출력 |
| --- | --- | --- |
| on | off | 오디오가 없는 VIDEO |
| on | on | 오디오가 없는 VIDEO + 추출한 AUDIO |
| off | on | 추출한 AUDIO만 출력 |
| off | off | 출력하지 않고 manifest에만 보존 |

V와 A가 모두 활성화된 경우 추출된 오디오의 기본 캡션은 비디오 캡션을 복사한다. 항목에 `audio_caption_override`가 있으면 그것을 우선한다.

오디오 제거는 가능하면 재인코딩하지 않는 remux를 사용한다. 사용하는 ComfyUI VIDEO 객체가 이미 무음 비디오를 표현할 수 있다면 불필요한 파일 생성을 피한다.

## 캡션과 LLM 경계

Director의 캡션은 사용자가 제공한 원본 설명 또는 hint다. Director는 이 문자열을 생성 프롬프트에 자동 삽입하지 않는다.

```text
Reference Director
  -> media lists
  -> raw caption lists
  -> manifest_json
        |
        v
Reference Analyzer / Prompt Composer
  -> VLM/LLM 분석
  -> 보강된 캡션 또는 최종 프롬프트
```

권장 책임 분리는 다음과 같다.

- Director: 파일 관리, 순서, 활성화, 캡션 입력, 편집, 타입별 리스트 출력
- Analyzer: 미디어와 사용자 캡션을 함께 분석해 보강된 설명 출력
- Prompt Composer: 분석 결과와 사용자 요청을 모델별 최종 프롬프트로 조립
- Generation node: Composer 출력을 명시적으로 받아 사용

manifest의 캡션에는 가능한 경우 출처를 기록한다.

```json
{
  "caption": {
    "text": "붉은 코트를 입은 인물",
    "source": "user"
  }
}
```

## manifest 설계

manifest는 미디어 payload를 감싸는 custom guide가 아니라 출력과 provenance를 설명하는 투명한 JSON이다.

예상 구조는 다음과 같다.

```json
{
  "version": 1,
  "visual_order": ["img-a", "vid-b", "img-c"],
  "audio_order": ["aud-d", "vid-b:audio"],
  "outputs": {
    "images": ["img-a", "img-c"],
    "audios": ["aud-d", "vid-b:audio"],
    "videos": ["vid-b"]
  },
  "items": {
    "img-a": {
      "kind": "image",
      "source": {
        "path": "reference_director/input/example.png",
        "mime": "image/png",
        "sha256": "..."
      },
      "caption": {
        "text": "붉은 코트를 입은 인물",
        "source": "user"
      },
      "enabled": {
        "visual": true
      },
      "edit": {
        "revision": 2
      }
    }
  }
}
```

### stable ID

- 항목 추가 시 UUID 또는 충돌 가능성이 충분히 낮은 stable ID를 생성한다.
- 파일명이나 배열 인덱스를 identity로 사용하지 않는다.
- 순서 변경 후에도 ID는 바뀌지 않는다.
- 파생 오디오는 원본 비디오 ID와의 관계를 manifest에 기록한다.

### 경로

- manifest에는 ComfyUI input/output/temp 기준의 상대 경로만 사용한다.
- 사용자 시스템의 절대 경로를 노출하지 않는다.
- 백엔드는 모든 경로를 canonicalize하고 허용된 ComfyUI 디렉터리 밖으로 나가지 못하게 검증한다.

## UI 구조

### 공통 레이아웃

노드 안에는 두 개의 독립 영역을 둔다.

```text
Reference Director
├─ toolbar
├─ Visual channel
│  └─ image/video cards in CSS Grid
└─ Audio channel
   └─ audio cards in CSS Grid/Flex
```

- 카드의 표시 비율은 모든 항목에 동일하게 적용한다.
- 표시 비율은 원본과 출력의 aspect ratio를 변경하지 않는다.
- Visual channel은 이미지와 비디오의 혼합 순서를 보존한다.
- Audio channel은 오디오 파일과 비디오에서 추출할 오디오를 표시한다.
- 두 영역의 정렬 순서는 독립적으로 관리한다.

### 카드 공통 기능

- 순서 번호
- 미디어 종류 badge
- 선택 상태
- 캡션 입력
- Ignore 또는 V/A toggle
- 제거 버튼
- drag handle
- 오류와 처리 상태
- 더블클릭 편집

### 드래그 앤 드롭

- 파일 drop과 카드 reorder를 구분한다.
- 카드 사이 삽입 위치를 명확히 표시한다.
- stable ID 기준으로 순서를 변경한다.
- reorder 중 원본 state를 반복 deep clone하지 않는다.
- drop 완료 시 한 번의 history command로 기록한다.
- 가능하면 키보드 기반 순서 이동 명령도 제공한다.

### 다중 선택

MVP에서는 단일 선택만으로 시작할 수 있다. 다중 선택을 추가하면 다음 범위로 제한한다.

- Shift/Ctrl 선택
- 일괄 Ignore
- 일괄 제거
- 선택 항목 연속 이동

서로 다른 미디어에 편집 recipe를 일괄 적용하는 기능은 초기 범위에서 제외한다.

## 렌더링 전략

### DOM-first

Nodes 2.0의 주 UI는 DOM과 CSS로 구현한다.

| UI 요소 | 구현 |
| --- | --- |
| 카드 grid | CSS Grid |
| 채널 레이아웃 | CSS Grid/Flex |
| 이미지/비디오 섬네일 | `<img>` 또는 제한적인 `<video>` |
| 캡션 | `<textarea>` |
| 상태와 제어 | DOM button, badge, input |
| 편집 modal | DOM dialog/root |

메인 노드 UI를 하나의 Canvas로 직접 그리지 않는다. 캡션 IME, focus, keyboard navigation, scroll, selection, tooltip과 접근성은 브라우저의 DOM 기능을 활용한다.

### Canvas island

Canvas는 다음 국소 기능에만 사용한다.

- 이미지 base/mask/tool overlay
- 브러시 erase/restore
- 이미지 합성 preview
- 오디오 waveform
- 필요한 경우 비디오 첫 프레임 capture
- Worker의 `OffscreenCanvas` 기반 preview 변환

카드의 정적 섬네일은 Canvas를 유지하지 않고 WebP URL을 사용하는 `<img>`로 표시한다.

### Nodes 2.0과 Legacy Canvas

- 두 모드에서 동일한 DOM widget과 직렬화 계약을 우선 사용한다.
- Legacy 전용 전체 Canvas UI를 별도로 만들지 않는다.
- mode 차이는 resize, zoom, mount/unmount lifecycle adapter로 격리한다.
- 극단적으로 zoom out된 경우 미디어 카드를 숨기고 개수 요약만 표시할 수 있다.
- Legacy에서 복잡한 노드 내 DOM이 불안정하면 노드에는 요약과 `Open Director` 버튼만 남기고 동일한 DOM modal을 연다.
- `onDrawForeground`를 이용한 전체 UI와 짧은 주기의 polling은 사용하지 않는다.

## 미리보기와 캐시

### 이미지

- 원본 대신 기본 최대 1 MPixel의 WebP proxy를 표시한다.
- `preview_max_pixels`는 노드 또는 전역 setting에서 조절할 수 있다.
- 가로 또는 세로 한 변 기준이 아니라 총 픽셀 수 기준으로 축소한다.
- 작은 이미지는 확대하지 않는다.
- proxy 설정은 출력 IMAGE와 실행 fingerprint에 영향을 주지 않는다.

권장 크기 계산:

```text
if width * height <= max_pixels:
    keep size
else:
    scale = sqrt(max_pixels / (width * height))
```

### 오디오

- 백엔드가 전체 오디오를 waveform 표시용으로 보내지 않는다.
- 200~500개 정도의 normalized peak 또는 min/max pair를 계산해 반환한다.
- waveform cache key는 source hash, crop revision, peak count로 구성한다.

### 비디오

- 첫 프레임 또는 첫 유효 프레임을 WebP/JPEG proxy로 생성한다.
- duration, 해상도, frame rate, audio track 유무를 metadata로 제공한다.
- 브라우저에서 매번 원본 비디오 전체를 읽어 thumbnail을 재생성하지 않는다.

### 저장 위치

- proxy와 waveform은 재생성 가능한 cache다.
- workflow state에는 cache key 또는 상대 URL만 기록한다.
- proxy 파일이나 waveform 배열을 base64로 직렬화하지 않는다.
- cache miss 시 비동기로 재생성한다.

## 이미지 편집기

더블클릭으로 node 밖의 modal을 연다.

### MVP 기능

- crop
- pan/zoom
- horizontal/vertical flip
- 투명 배경으로 지우기
- 지운 영역 복원
- 단색 배경 칠하기
- brush size와 opacity
- Undo/Redo
- Apply/Cancel

자동 AI 배경 제거와 inpaint는 초기 핵심 범위에서 제외하고 선택적 후속 기능으로 둔다.

### Canvas 계층

```text
editor viewport
├─ base image canvas
├─ mask/edit canvas
└─ tool/selection overlay canvas
```

도구 버튼과 속성 panel은 DOM으로 구현한다.

### 비파괴 recipe

```json
{
  "crop": {
    "x": 0.1,
    "y": 0.0,
    "width": 0.8,
    "height": 1.0
  },
  "transform": {
    "scale": 1.0,
    "offset_x": 0.0,
    "offset_y": 0.0,
    "rotation": 0,
    "flip_x": false,
    "flip_y": false
  },
  "mask_file": "reference_director/edits/abc123-mask.png",
  "background": {
    "mode": "transparent",
    "color": "#ffffff"
  },
  "revision": 4
}
```

- crop 좌표는 원본 크기에 독립적인 normalized 좌표로 저장한다.
- 큰 pixel mask는 workflow JSON이 아니라 content-addressed sidecar 파일로 저장한다.
- Apply 전까지의 편집은 임시 상태다.
- Apply 시 하나의 새로운 revision으로 커밋한다.
- 원본 파일은 항상 유지한다.

## 오디오 편집기

- 더블클릭하면 확대된 waveform modal을 연다.
- 시작과 끝 handle로 crop한다.
- crop 값은 초 단위로 저장하되 source duration 검증을 수행한다.
- 최소 crop 길이와 허용 범위를 백엔드에서 다시 검증한다.
- 타임라인 동기화가 없으므로 다른 미디어의 crop 위치와 연동하지 않는다.
- 초기 버전에서는 fade, gain, denoise를 지원하지 않는다.

## 비디오 카드와 편집

초기 비디오 UI는 전체 video editor가 아니라 metadata와 활성화 제어에 집중한다.

- 첫 프레임 proxy
- duration badge
- V toggle
- A toggle
- 사용자 캡션
- 선택적 `audio_caption_override`
- 필요하면 단일 시작/끝 crop

영상 crop을 추가하더라도 프레임 단위 timeline UI는 만들지 않는다. 오디오 crop과 동일한 독립 구간 선택으로 제한한다.

## Undo/Redo

Undo/Redo는 두 층으로 나눈다.

### Director history

- 항목 추가/제거
- reorder
- caption 변경의 의미 있는 commit
- V/A toggle
- 편집 revision 적용

전체 state와 base64 preview를 매번 deep clone하지 않고 command 또는 가벼운 state snapshot을 사용한다.

### Editor-local history

- brush stroke
- mask clear/invert
- crop/transform 변경
- background 설정

modal을 닫거나 Apply하면 editor-local history는 폐기할 수 있다. workflow에 history 자체를 직렬화하지 않고 현재 커밋된 state만 저장한다.

## 프론트엔드 도구와 구조

Reference Director 구현 전에 Vite와 strict TypeScript를 다시 도입하는 것을 권장한다. 현재의 소규모 JS 기능에는 빌드 도구가 필수는 아니지만 Director의 상태, editor, Worker와 API 경계는 TypeScript의 이점이 크다.

권장 구조:

```text
frontend/
├─ src/
│  ├─ index.ts
│  ├─ existing/
│  │  ├─ ollama-connectivity.ts
│  │  └─ llama-cpp-widget-states.ts
│  └─ reference-director/
│     ├─ extension.ts
│     ├─ types.ts
│     ├─ state.ts
│     ├─ serialization.ts
│     ├─ api.ts
│     ├─ history.ts
│     ├─ components/
│     ├─ editors/
│     └─ workers/
├─ test/
├─ tsconfig.json
└─ vite.config.ts

dist/
├─ index.js
└─ reference-director.css
```

루트 Python shim은 다음처럼 빌드 결과만 노출한다.

```python
WEB_DIRECTORY = "./dist"
```

### 빌드 원칙

- 설치 사용자는 Node.js, TypeScript 또는 Vite를 실행할 필요가 없어야 한다.
- 빌드된 `dist/`를 배포 패키지에 포함한다.
- ComfyUI가 모든 `.js`를 extension entry로 자동 로드하는 점을 고려해 불필요한 hashed chunk를 만들지 않는다.
- 가능한 한 고정된 단일 entry bundle을 사용한다.
- Worker는 inline worker 또는 자동 extension entry로 오인되지 않는 asset으로 출력한다.
- `/scripts/app.js`와 `/scripts/api.js`만 안정적인 ComfyUI public import 경계로 취급한다.
- ComfyUI 내부 Vue/domWidget 구현을 직접 import하지 않는다.
- 기존 두 JS 파일은 규모가 작으므로 동일한 TypeScript build로 이전한다.

### UI 프레임워크

- 첫 구현은 vanilla TypeScript와 DOM을 기본으로 한다.
- reducer와 state model은 렌더러와 분리한다.
- React/Preact가 필요해지면 편집 modal 또는 특정 DOM widget 내부에만 root를 mount한다.
- 프레임워크가 LiteGraph/Nodes 2.0 node lifecycle 전체를 소유하게 하지 않는다.
- Nodes 2.0이 Vue 기반이라는 이유만으로 ComfyUI 내부 Vue API에 결합하지 않는다.

## 프론트엔드 상태 모델

TypeScript discriminated union을 사용한다.

```ts
type MediaItem = ImageItem | AudioItem | VideoItem;

interface BaseItem {
  id: string;
  caption: string;
}

interface ImageItem extends BaseItem {
  kind: "image";
  visualEnabled: boolean;
  edit: ImageEditRecipe;
}

interface AudioItem extends BaseItem {
  kind: "audio";
  audioEnabled: boolean;
  crop: TimeRange;
}

interface VideoItem extends BaseItem {
  kind: "video";
  visualEnabled: boolean;
  audioEnabled: boolean;
  crop: TimeRange;
  audioCaptionOverride?: string;
}
```

### 직렬화

- hidden backing widget에는 versioned JSON state만 저장한다.
- `JSON.parse(...) as DirectorState`만으로 신뢰하지 않는다.
- 런타임 validator와 migration을 적용한다.
- 저장 state, 임시 UI state, derived cache state를 분리한다.

```ts
interface DirectorState {
  version: 1;
  items: Record<string, MediaItem>;
  visualOrder: string[];
  audioOrder: string[];
  ui: DirectorUiPreferences;
}
```

다음은 직렬화하지 않는다.

- DOM element
- `File`, `Blob`, `ImageBitmap`
- Canvas context
- decoded audio buffer
- base64 preview
- Undo/Redo history
- 열려 있는 modal과 hover/drag 임시 상태

## ComfyUI 프론트엔드 통합

공개 extension API 중심으로 구현한다.

- `app.registerExtension`
- `getCustomWidgets` 또는 필요한 공식 node hook
- `node.addDOMWidget`
- widget `serializeValue`
- widget `beforeQueued`
- `api.fetchApi`
- 공식 toast/dialog API

다음 패턴은 피한다.

- 전역 Canvas prototype 변경
- 다른 extension이 사용하는 node prototype의 공격적인 hijack
- `onDrawForeground` 전체 UI
- 200~300ms polling으로 state 동기화
- deprecated `scripts/ui`
- 내부 `scripts/domWidget`, `scripts/utils`, `scripts/changeTracker`에 대한 강한 결합

입력 이벤트는 Director의 interactive root 안에서만 처리하고 graph pan/zoom과 충돌하지 않게 한다. 노드 삭제, workflow 교체, modal close 시 event listener와 Worker를 명시적으로 정리한다.

## 백엔드 구조

현재 저장소 규칙에 따라 Python 코드는 `backend/` 아래에 둔다. 루트 `__init__.py`는 thin ComfyUI entry shim으로 유지한다.

예상 구조:

```text
backend/
├─ nodes/
│  └─ reference_director.py
├─ core/
│  ├─ reference_contract.py
│  ├─ reference_manifest.py
│  ├─ reference_paths.py
│  └─ reference_edits.py
└─ routes/
   └─ reference_director.py
```

실제 저장소의 registration 구조에 맞춰 파일 위치는 구현 시 조정할 수 있다.

### pure contract 계층

ComfyUI import가 없는 순수 모듈에 다음을 둔다.

- state/manifest dataclass 또는 TypedDict
- schema version 검사
- stable ID와 order 검증
- caption/media alignment
- enabled 상태 해석
- crop 범위 검증
- media count, 파일 크기, duration 제한
- manifest 생성

### 미디어 처리 계층

- 이미지 decode와 비파괴 recipe 적용
- 1 MPixel WebP proxy 생성
- 오디오 metadata, crop, waveform peak 생성
- 비디오 metadata와 첫 프레임 추출
- 비디오 embedded audio 추출
- 확정될 경우 무음 video remux

### API route

예상 route 범위:

```text
POST /reference_director/upload
POST /reference_director/metadata
POST /reference_director/image_proxy
POST /reference_director/waveform
POST /reference_director/apply_edit
```

정확한 route 수는 구현 중 합칠 수 있다. 모든 route는 `api.fetchApi`로 호출한다.

## 보안과 자원 제한

- 입력 경로는 `realpath`/canonical path로 검증한다.
- ComfyUI가 허용한 input/temp/output 범위를 벗어나는 경로를 거부한다.
- 업로드 파일명은 신뢰하지 않는다.
- MIME, 확장자, magic bytes를 가능한 범위에서 교차 확인한다.
- 업로드와 base64 body에 크기 제한을 둔다.
- multipart 파일 전체를 무제한 메모리에 읽지 않는다.
- 이미지 pixel 수, 오디오 duration, 비디오 duration에 상한을 둔다.
- 압축 폭탄과 비정상 metadata를 고려한다.
- AI 모델 dependency를 runtime에 `pip install`하지 않는다.
- 삭제와 cache cleanup은 검증된 전용 디렉터리 안에서만 수행한다.
- 오류 응답에 절대 경로나 사용자 데이터를 노출하지 않는다.

## 캐싱과 fingerprint

### 실행 결과에 영향을 주는 항목

- source identity/hash
- enabled 상태
- output order
- caption
- crop
- image edit revision
- 비디오 오디오 정책

### 실행 결과에 영향을 주지 않는 항목

- 카드 열 수
- 카드 표시 비율
- 노드 내 scroll 위치
- 선택 상태
- hover 상태
- preview 최대 픽셀 수
- waveform 표시 peak 수
- modal 크기와 위치

UI-only 설정 변경으로 백엔드 실행 cache가 불필요하게 무효화되지 않도록 fingerprint를 분리한다.

## 구현 단계

### Phase 0: 기술 검증

- Vite + TypeScript 최소 build 복구
- 기존 JS 두 파일의 build 진입점 이전
- Nodes 2.0과 Legacy에서 동일한 `addDOMWidget` mount 검증
- state 직렬화/복원 smoke test
- node resize, zoom, 삭제 시 cleanup 검증

### Phase 1: 출력 계약과 기본 Director

- V3 node schema와 list outputs
- versioned state validator
- 이미지/오디오/비디오 항목 추가와 제거
- 타입별 출력과 캡션 정렬
- manifest 생성
- Ignore 처리
- 서로 다른 IMAGE 해상도 유지 검증

### Phase 2: DOM UI

- Visual/Audio channel
- 고정 비율 카드 grid
- 캡션 입력
- V/A toggle
- drag reorder
- 선택과 오류 표시
- workflow 저장/복원

### Phase 3: proxy와 metadata

- 이미지 WebP proxy
- 오디오 waveform peak
- 비디오 첫 프레임과 metadata
- content-addressed cache
- async loading/error/retry UI

### Phase 4: 이미지 편집

- modal과 stacked Canvas
- crop/transform
- erase/restore mask
- background transparent/solid
- editor-local Undo/Redo
- 비파괴 recipe와 sidecar

### Phase 5: 오디오와 비디오

- 오디오 crop modal
- 비디오 V/A 정책 확정 및 구현
- embedded audio 추출
- 필요한 경우 무음 video remux
- 파생 오디오 caption 규칙

### Phase 6: 통합과 배포

- Analyzer/Prompt Composer 연결 예제
- Nodes 2.0/Legacy 호환 테스트
- package build와 `dist/` 포함
- workflow 예제
- 사용자 문서
- 성능, 경로 안전성과 자원 제한 검증

## 테스트 계획

### Python

`uv run pytest`를 사용한다.

- state schema validation
- manifest 생성과 stable ID
- 이미지/캡션, 오디오/캡션, 비디오/캡션 정렬
- Ignore filtering
- 서로 다른 이미지 해상도
- path traversal 거부
- crop 범위와 duration 제한
- proxy가 1 MPixel 한도를 넘지 않는지
- 작은 proxy source를 확대하지 않는지
- 원본 파일 불변성
- video/audio 파생 관계

### TypeScript unit test

- reducer
- reorder command
- V/A toggle
- Undo/Redo
- serialize/deserialize
- version migration
- invalid state fallback
- UI-only state와 execution state 분리
- output ID map 생성

### 브라우저 smoke test

- Nodes 2.0에서 노드 생성
- Legacy Canvas에서 노드 생성
- 파일 drop
- 카드 reorder
- 캡션 IME 입력
- workflow 저장 후 reload
- modal open/close와 cleanup
- queue 직전 serialized state
- 여러 노드 instance의 상태 격리

실제 ComfyUI E2E harness는 기본 contract와 reducer가 안정화된 뒤 최소 범위로 추가한다.

## 수용 기준

다음 조건이 모두 충족되면 최초 기능 버전을 완료로 본다.

1. 서로 다른 해상도의 이미지가 resize 없이 별도 IMAGE list 항목으로 출력된다.
2. 각 종류의 미디어와 캡션 리스트 길이가 항상 같다.
3. 이미지와 비디오의 혼합 시각 순서를 manifest에서 복원할 수 있다.
4. Ignore 항목은 출력에서 빠지지만 manifest에 상태와 ID가 남는다.
5. 노드 카드의 고정 비율이나 preview 크기를 바꿔도 실행 미디어가 바뀌지 않는다.
6. workflow JSON에 원본/preview base64가 포함되지 않는다.
7. 이미지 편집 후 원본 파일이 변경되지 않는다.
8. editor Undo/Redo가 Apply 전 편집을 정확히 복원한다.
9. Nodes 2.0에서 DOM grid, 캡션과 drag가 정상 작동한다.
10. Legacy Canvas에서 최소한 동일한 state 편집과 modal 접근이 가능하다.
11. Director 캡션이 generation prompt에 자동 삽입되지 않는다.
12. 사용자가 Node.js build 없이 배포된 custom node를 설치해 사용할 수 있다.

## 구현 전에 확정할 사항

1. VIDEO 출력의 공식 데이터 형태와 최소 지원 ComfyUI/frontend 버전
2. VIDEO에서 embedded audio를 항상 제거할지 여부
3. 무음 video 생성 시 remux 결과의 cache 위치와 lifetime
4. 최대 이미지/오디오/비디오 항목 수와 파일 크기/duration 제한
5. 이미지 편집 MVP에 rotate와 AI 배경 제거를 포함할지 여부
6. Director 내부 다중 선택을 최초 버전에 포함할지 여부
7. vanilla TypeScript만 사용할지 편집 modal에 React/Preact를 사용할지 여부
8. WebP proxy 설정을 노드별로 둘지 ComfyUI 전역 setting으로 둘지 여부
9. manifest에 source 상대 경로를 공개할지 opaque source ID만 공개할지 여부
10. 하위 Analyzer/Prompt Composer 노드를 이번 기능과 함께 제공할지 별도 단계로 둘지 여부

## 참고 구현과 채택 범위

### DaSiWa MiniMax H3 Director

- 참고: 두 채널 UI, media drop, V/A/V+A 개념, PyAV crop/추출, 입력 경로 검증
- 채택하지 않음: 이미지/비디오/오디오 payload가 들어간 opaque guide, 사용자 캡션의 직접 prompt 조립, video의 IMAGE frame tensor 변환, 전체 state 내 base64 thumbnail/waveform, 전체 UI prototype patch와 polling
- 소스: [helper_minimax_h3_director.py](https://github.com/darksidewalker/ComfyUI-DaSiWa-Nodes/blob/main/nodes/helper_minimax_h3_director.py), [minimax_h3_director.js](https://github.com/darksidewalker/ComfyUI-DaSiWa-Nodes/blob/main/js/minimax_h3_director.js)

### ComfyUI Multi-Image Loader

- 참고: drag reorder, 편집 modal, stacked Canvas, normalized crop, mask brush, Worker, sidecar 편집 파일
- 채택하지 않음: 공통 canvas 크기와 tensor batch, source overwrite, workflow state의 큰 base64 snapshot, 전역 Canvas prototype patch, runtime dependency 설치
- 소스: [nodes.py](https://github.com/Latentnaut/ComfyUI-Multi-Image-Loader/blob/main/nodes.py), [multi_image_loader.js](https://github.com/Latentnaut/ComfyUI-Multi-Image-Loader/blob/main/web/multi_image_loader.js)

### 공식 ComfyUI

- [Nodes 2.0](https://docs.comfy.org/interface/nodes-2)
- [JavaScript extensions](https://docs.comfy.org/custom-nodes/js/javascript_overview)
- [Comfy hooks](https://docs.comfy.org/custom-nodes/js/javascript_hooks)
- [Comfy objects and DOM widgets](https://docs.comfy.org/custom-nodes/js/javascript_objects_and_hijacking)
- [ComfyUI React/TypeScript extension template](https://github.com/Comfy-Org/ComfyUI-React-Extension-Template)

