# Reference Loader 저장소 병합 계획

## 문서 상태

- 작성일: 2026-08-15
- 소스 저장소: `ComfyUI-Ollama-Multimodal`
- 소스 브랜치: `multi-image-selector`
- 확인한 소스 HEAD: `5802e34b965e908a1f8f612567c2e0379c7e7477`
- 대상 저장소: <https://github.com/craftingmod/ComfyUI-Reference-Loader>
- 확인한 대상 `main`: `7d211b2819e3acb7bbf6901e2c55d583999ee415`
- 대상 상태: ComfyUI V3 Python, Bun frontend, Registry ZIP 및 CI를 포함한 템플릿 초기 커밋

이 문서는 현재 `Reference Director` 구현을 독립 패키지인 `Reference Loader`로 옮기는 절차를 정의한다. 소스 작업 트리는 작성 시점에 커밋되지 않은 변경을 포함하므로 위 소스 HEAD를 최종 이식 기준으로 사용하면 안 된다. 먼저 현재 구현을 검증하고 하나의 명시적인 기준 커밋으로 고정해야 한다.

## 목표

1. Reference Loader를 Ollama, llama.cpp 및 프롬프트 기능과 무관한 단일 배포 가능 ComfyUI custom node pack으로 만든다.
2. 새 저장소가 제공하는 패키징, 로컬 배포, CI 및 Comfy Registry 릴리스 기반은 유지한다.
3. 기존 Reference Director의 동작과 출력 계약을 보존한 뒤 이름과 영구 식별자를 한 번에 정리한다.
4. 소스 저장소와 대상 저장소를 동시에 설치하지 않아도 기존 기능을 완전히 검증할 수 있게 한다.
5. 새 저장소가 검증되기 전에는 소스 저장소에서 구현을 제거하지 않는다.

## 병합 전략

대상 저장소를 기준으로 선택적 코드 이식을 수행한다. 두 저장소에 다음 명령을 사용하는 방식은 권장하지 않는다.

```shell
git merge --allow-unrelated-histories
```

이를 사용하면 Ollama/llama.cpp 코드와 이전 패키지 메타데이터가 대상 저장소에 들어오고, 대상 템플릿의 빌드·배포 구조와 대량 충돌한다. Reference Loader 변경 이력도 소스 저장소의 다른 기능 변경과 일부 섞여 있으므로 대상 저장소의 깨끗한 초기 이력 위에 기능 단위 커밋을 새로 만드는 편이 낫다.

권장 커밋 흐름은 다음과 같다.

1. `chore: initialize Reference Loader metadata`
2. `feat: add Reference Loader backend and routes`
3. `feat: add Reference Loader frontend and editors`
4. `refactor: rename Director contracts to Loader`
5. `docs: add Reference Loader guide and workflow`
6. `test: complete standalone packaging and release validation`

## 0단계: 영구 이름과 계약 확정

공개 후 변경하기 어려운 식별자를 이식 전에 확정한다.

| 항목 | 권장 값 | 비고 |
| --- | --- | --- |
| 저장소 | `ComfyUI-Reference-Loader` | 이미 생성됨 |
| Project ID | `reference-loader` | `pyproject.toml`, `package.json`, frontend 상수에서 공유 |
| 표시 이름 | `Reference Loader` | Registry 및 노드 UI |
| Python node ID | `Alyac_ReferenceLoader` | 공개 후 변경 금지 |
| Python 클래스 | `ReferenceLoaderNode` | 내부 이름 |
| Extension 클래스 | `ReferenceLoaderExtension` | 내부 이름 |
| ComfyUI 카테고리 | `media/reference` | Ollama 경로 제거 |
| Frontend extension | `reference-loader.extension` | 전역 충돌 방지 |
| API prefix | `/reference_loader` 또는 `/alyac/reference_loader` | 최종 하나를 선택해 Python/TypeScript에서 공유 |
| 관리 저장소 | `input/reference_loader` | 개발 workflow 호환이 필요 없다는 전제 |
| State input | `loader_state` | `director_state`를 공개 계약으로 남기지 않음 |
| State version | `1` | 새 독립 계약으로 시작 |

결정 사항:

- 출력 이름 `images`, `image_captions`, `audios`, `audio_captions`, `videos`, `video_captions`, `manifest_json`은 유지한다.
- VIDEO는 원본 컨테이너의 내장 오디오를 보존한다.
- 새 VIDEO의 별도 AUDIO 출력은 기본 비활성화 상태를 유지한다.
- 이미지별 독립 해상도와 list output 계약을 유지하며 batch, montage 또는 prompt composer를 추가하지 않는다.
- 개발 단계 workflow와 `input/reference_director` 파일은 자동 마이그레이션하지 않는다. 필요하면 다시 업로드한다.

## 1단계: 소스 구현 동결

대상 저장소 작업을 시작하기 전에 현재 저장소에서 다음을 완료한다.

- [ ] `docs/TESTING.md`를 현재 동작과 맞춘다.
  - Image Editor 기본 Interaction은 View다.
  - 모든 새 VIDEO는 A가 기본 비활성화이고 무음 VIDEO는 A 자체를 사용할 수 없다.
- [ ] 현재 변경 전체에 `bun run check:frontend`를 실행한다.
- [ ] 현재 변경 전체에 `uv run pytest`를 실행한다.
- [ ] `git diff --check`를 실행한다.
- [ ] Reference Loader 이식 기준 커밋을 만든다.
- [ ] 기준 커밋에 `reference-loader-source-v1` 같은 로컬 또는 원격 tag를 남긴다.
- [ ] 기준 commit SHA를 이 문서의 소스 기준에 갱신한다.

이 단계가 끝나기 전에는 작업 트리 파일을 직접 대상 저장소로 복사하지 않는다. 그렇지 않으면 어떤 변경이 이식됐는지 재현할 수 없다.

## 2단계: 대상 템플릿 초기화

대상 저장소의 템플릿 구조와 릴리스 스크립트를 유지한다. Comfy Registry Publisher ID가 현재 패키지와 같은 `alyac`이라는 전제의 초기화 예시는 다음과 같다.

```powershell
@(
  "reference-loader",
  "Reference Loader",
  "craftingmod",
  "ComfyUI-Reference-Loader",
  "alyac"
) | bun run init:template

uv lock
bun install
```

초기화 후 다음을 별도 커밋으로 만든다.

- [ ] `pyproject.toml`의 project name, repository, PublisherId, DisplayName 및 Icon 확인
- [ ] `package.json`의 name과 설명 확인
- [ ] `frontend/src/constants.ts`의 ID와 이름 확인
- [ ] `assets/icon.svg` 교체 또는 임시 아이콘임을 명시
- [ ] `LICENSE` 저작권 표기 확인
- [ ] `bun run release:check`가 template placeholder만 이유로 실패하지 않는 상태 확보

템플릿의 다음 기반은 유지한다.

- `.comfyignore` allowlist 패키징
- `dist/` frontend 산출물
- `scripts/build-custom-nodes.ts`
- `scripts/deploy-dev.ts`와 `scripts/deploy-local.ts`
- CI 및 Registry publish workflow
- Ruff, Oxlint 및 Oxfmt 검사

## 3단계: 백엔드 이식

### 파일 매핑

| 소스 | 대상 |
| --- | --- |
| `backend/nodes/reference_director.py` | `backend/nodes/reference_loader.py` |
| `backend/reference_routes.py` | `backend/reference_routes.py` |
| `backend/core/reference_contract.py` | `backend/core/reference_contract.py` |
| `backend/core/reference_manifest.py` | `backend/core/reference_manifest.py` |
| `backend/core/reference_media.py` | `backend/core/reference_media.py` |
| `backend/core/reference_background.py` | `backend/core/reference_background.py` |
| `tests/backend/test_reference_contract.py` | `tests/backend/test_reference_contract.py` |
| `tests/backend/test_reference_director.py` | `tests/backend/test_reference_loader.py` |
| `tests/backend/test_reference_media.py` | `tests/backend/test_reference_media.py` |
| `tests/backend/test_reference_routes.py` | `tests/backend/test_reference_routes.py` |

### 작업 순서

1. 동작 변경 없이 백엔드 파일과 테스트를 먼저 복사한다.
2. 대상의 예제 노드 `example_normalize_text.py`와 예제 테스트를 제거한다.
3. `backend/__init__.py`를 Reference Loader 전용 V3 extension으로 바꾼다.
4. extension entrypoint에서 Reference Loader route를 한 번만 등록한다.
5. 루트 `__init__.py`는 `WEB_DIRECTORY = "./dist"`와 얇은 `comfy_entrypoint()`만 유지한다.
6. 소스 저장소의 전체 `backend/core/__init__.py`는 복사하지 않는다. Reference Loader가 쓰는 모듈만 명시적으로 import한다.
7. `tests/conftest.py`와 루트 `conftest.py`는 덮어쓰지 말고 대상 템플릿의 ComfyUI test double과 소스 테스트 fixture를 병합한다.

### 메타데이터와 dependency

- `[project.optional-dependencies].rembg`를 옮긴다.
- Pillow, NumPy, torch 및 PyAV는 ComfyUI 제공 dependency로 취급하고 런타임 필수 항목에 중복 추가하지 않는다.
- 독립 CI에서 이미지 route 테스트가 skip되지 않도록 Pillow는 `dev` dependency에 추가한다.
- 실제 코드가 Python 3.11에서도 동작해야 한다면 별도 CI로 확인한 후 `requires-python`을 낮춘다. 검증 전에는 템플릿의 Python 3.12를 유지한다.
- `[tool.comfy].requires-comfyui = ">=0.19.3"`를 추가한다.

### 템플릿 release validator 수정

현재 대상 저장소의 `scripts/validate-release.ts`는 backend identity를 다음 예제 파일에서 읽는다.

```text
backend/nodes/example_normalize_text.py
```

예제 노드를 제거하면 release validation이 깨진다. 다음 중 하나로 수정한다.

1. `backend/nodes/reference_loader.py`의 `PROJECT_ID`와 `PROJECT_NAME`을 읽게 한다.
2. 더 권장되는 방식으로, backend identity를 별도 `backend/constants.py`에 두고 extension과 validator가 그 파일을 기준으로 검사하게 한다.

이 변경에 맞춰 `frontend/test/release-validation.test.ts`도 갱신한다.

### 백엔드 중간 검증

```shell
bun run test:backend
bun run lint
bun run fmt:check
```

이 시점에는 frontend를 아직 연결하지 않아도 node schema, state contract, output alignment, media loader 및 route 테스트가 통과해야 한다.

## 4단계: 프론트엔드 이식

### 파일 매핑

| 소스 | 대상 |
| --- | --- |
| `frontend/src/reference-director/**` | `frontend/src/reference-loader/**` |
| `frontend/src/comfyui.ts` | 필요한 타입만 대상 frontend에 병합 |
| `frontend/src/comfyui-app.d.ts` | 대상 공식 frontend type과 충돌하지 않는 범위에서 병합 |
| `frontend/src/comfyui-api.d.ts` | 대상 공식 frontend type과 충돌하지 않는 범위에서 병합 |
| `frontend/test/api.test.ts` | `frontend/test/reference-loader-api.test.ts` |
| `frontend/test/dom.test.ts` | `frontend/test/reference-loader-dom.test.ts` |
| `frontend/test/editor.test.ts` | `frontend/test/reference-loader-editor.test.ts` |
| `frontend/test/extension.test.ts` | `frontend/test/reference-loader-extension.test.ts` |
| `frontend/test/state.test.ts` | `frontend/test/reference-loader-state.test.ts` |
| `frontend/test/setup.ts` | 대상 Bun test preload에 병합 |

### 빌드 경계

대상 저장소는 Vite 대신 Bun bundler로 `dist/index.js`를 만든다. Vite 설정을 그대로 복사하지 않고 다음 계약을 Bun build에서 재현한다.

- `/scripts/app.js`와 `/scripts/api.js`는 external import다.
- 배포 frontend는 `dist/index.js` 하나만으로 동작한다.
- Reference Loader CSS는 JS에서 한 번만 설치되며 별도 CSS 로딩에 의존하지 않는다.
- build가 생성한 추가 asset이 필요하다면 `.comfyignore`와 Registry archive 검사를 함께 갱신한다.
- CSS inline 방식은 Bun의 text loader 또는 build-time 변환으로 구현하되, 먼저 현재 UI 동작을 보존하고 bundler 리팩터링을 별도 변경으로 둔다.

`frontend/src/index.ts`의 최종 책임은 다음뿐이다.

1. ComfyUI `app`과 `api` import
2. Reference Loader CSS 설치
3. `registerReferenceLoader(app, api)` 호출

Ollama connectivity 및 llama.cpp widget state 등록은 복사하지 않는다.

### 테스트 환경

- 현재 frontend 테스트가 사용하는 Happy DOM dependency와 preload 설정을 대상 `package.json` 및 `bunfig.toml`에 병합한다.
- 대상 템플릿의 build, release, local deployment 테스트는 유지한다.
- TypeScript와 formatter 버전은 우선 대상 lockfile을 따른다.
- TypeScript 7에서 기존 코드가 실패할 경우 오류를 먼저 수정하고, 단기적으로 버전을 낮춰야 한다면 별도 근거와 follow-up을 남긴다.

### 프론트엔드 중간 검증

```shell
bun run typecheck
bun run test:frontend
bun run build
```

생성된 `dist/index.js`에서 Reference Loader 이외의 Ollama/llama.cpp extension 등록이 없어야 한다.

## 5단계: Director에서 Loader로 명칭 정리

백엔드와 프론트엔드가 대상 저장소에서 먼저 통과한 뒤, 동작 보존 rename을 별도 커밋으로 수행한다. 이식과 rename을 동시에 하면 실패 원인을 구분하기 어렵다.

정리 대상:

- `ReferenceDirectorNode` → `ReferenceLoaderNode`
- `DirectorState` → `ReferenceLoaderState` 또는 `LoaderState`
- `ReferenceDirectorController` → `ReferenceLoaderController`
- `registerReferenceDirector` → `registerReferenceLoader`
- `director_state` → `loader_state`
- `reference-director` 디렉터리와 테스트 이름 → `reference-loader`
- `.reference-director`와 `.rd-*` CSS class → `.reference-loader`와 `.rl-*`
- frontend extension name과 style element ID
- Python/TypeScript API base 상수
- route prefix의 `ollama_multimodal/reference_director`
- `input/reference_director` 관리 경로와 cache namespace
- 상태 메시지, aria label, tooltip, 문서 및 workflow의 표시 이름
- `REFERENCE_DIRECTOR_*` 상수 → `REFERENCE_LOADER_*`

rename 후 다음 검색 결과를 검토한다.

```shell
rg -n -i "ollama|llama|reference[ _-]?director|\brd[-_]" . \
  -g '!build/**' \
  -g '!dist/**' \
  -g '!CHANGELOG.md'
```

역사 설명이나 migration 문서가 아니라면 결과가 없어야 한다. 새 저장소는 개발 단계이므로 old node ID, old route 및 old state에 대한 compatibility shim은 추가하지 않는다.

## 6단계: 문서, workflow 및 배포 파일 이식

### 이식 대상

- `docs/REFERENCE_DIRECTOR.md`를 `docs/REFERENCE_LOADER.md`로 이름과 내용을 정리한다.
- `docs/TESTING.md`의 Reference Loader 수동 smoke 절차를 대상 템플릿 검사 순서와 합친다.
- `workflows/Reference_Director.json`을 `workflows/Reference_Loader.json`으로 바꾸고 새 node ID/state input으로 다시 저장한다.
- README는 Reference Loader 전용 설명, 설치, 출력 계약, 한계 및 선택적 rembg 설치만 남긴다.
- `THIRD_PARTY_NOTICES.md`와 `LICENSE`는 실제 포함 코드 및 dependency에 맞게 검토한다.
- `assets/icon.svg`를 새 프로젝트 정체성에 맞춘다.
- `.comfyignore`에 `docs/`와 `workflows/`를 배포할지 결정한다. 런타임에 불필요하면 GitHub에만 유지하고 Registry ZIP에서는 제외할 수 있다.

### 이식하지 않을 문서

- Ollama, llama.cpp, MiniMax prompt 관련 README와 문서
- 기존 전체 `CHANGELOG.md` 역사
- `REFERENCE_DIRECTOR_PLAN.md`의 구현 전 설계 문서 전체

필요한 설계 원칙만 새 `docs/ARCHITECTURE.md`에 현재 구현 기준으로 짧게 옮긴다.

## 7단계: 전체 검증

대상 저장소 AGENTS와 CI 순서에 맞춰 다음을 모두 실행한다.

```shell
bun install --frozen-lockfile
uv sync --locked --group dev
bun run fmt:check
bun run lint
bun run typecheck
bun run test:unit
bun run build
bun run release:check
bun run build:custom-node
git diff --check
```

추가 확인:

- [ ] Python reference test가 skip 없이 실행된다.
- [ ] frontend state/DOM/editor/API 테스트가 모두 실행된다.
- [ ] `dist/index.js`만으로 frontend가 등록된다.
- [ ] Registry ZIP에 루트 `__init__.py`, `backend/`, `dist/`, metadata 및 필요한 asset이 포함된다.
- [ ] ZIP에 source frontend, test, cache, `.env.local` 또는 개발용 ComfyUI 경로가 포함되지 않는다.
- [ ] node schema의 모든 list output과 caption output 순서가 일치한다.
- [ ] `manifest_json`에 base64 또는 절대 경로가 없다.

## 8단계: 실제 ComfyUI 단독 smoke test

동일 node/route 중복을 피하려면 기존 `ComfyUI-Ollama-Multimodal` 설치에서 Reference Director를 제거하거나 전체 기존 pack을 잠시 비활성화한 뒤 새 저장소만 설치한다.

최소 smoke 범위:

1. Nodes 2.0과 Legacy Canvas에서 Reference Loader 생성
2. 이미지, 투명 이미지, 오디오, 유음 VIDEO 및 무음 VIDEO 업로드
3. proxy, waveform, Grid playback 및 trim modal 확인
4. 이미지 View/Crop/Mask, flip, background 및 Restore original 확인
5. rembg 미설치 오류와 설치 후 preview/Apply 확인
6. 종류별 reorder, enable toggle, caption 및 출력 번호 확인
7. MPixel 제한과 alpha composite socket/widget 실행 확인
8. workflow 저장, ComfyUI 재시작 및 복원
9. 실제 IMAGE/AUDIO/VIDEO list와 caption list 정렬 확인
10. Registry ZIP을 별도 custom_nodes 디렉터리에 설치해 같은 동작 확인

Legacy Canvas의 DOM 상호작용 감각이 Nodes 2.0보다 뻑뻑한 점은 기능 결함이 아니라 알려진 UI 제한으로 문서화한다. 별도 Canvas 구현은 범위에 추가하지 않는다.

## 9단계: 소스 저장소 정리와 전환

새 저장소의 단독 smoke test가 끝난 후에만 기존 저장소에서 Reference Director를 제거한다.

제거 범위:

- backend node, core reference 모듈 및 reference routes
- extension과 route registration
- frontend Reference Director 소스와 entry registration
- Reference Director 전용 테스트
- README, changelog, docs 및 workflow 항목
- 기존 `web/index.js`에서 Reference Director frontend가 빠지도록 재빌드
- 기존 pyproject의 선택적 rembg dependency가 다른 기능에서 사용되지 않으면 제거

기존 저장소에는 다음 안내만 남길 수 있다.

> Reference Loader는 `craftingmod/ComfyUI-Reference-Loader`로 분리되었습니다.

두 저장소가 같은 node ID 또는 API route를 동시에 등록하는 과도기는 만들지 않는다. 전환 커밋과 새 저장소 최초 release를 가까운 시점에 배포한다.

## Rollback

1. 소스 저장소의 `reference-loader-source-v1` tag를 유지한다.
2. 새 저장소의 분리 작업은 단계별 커밋으로 유지한다.
3. 실제 ComfyUI에서 중대한 문제가 발견되면 기존 pack 제거 커밋을 되돌리지 않고, 새 저장소 설치를 비활성화한 뒤 기준 tag의 기존 pack으로 복귀한다.
4. 새 저장소 수정 후 전체 검증과 단독 smoke를 다시 수행한다.

## 완료 기준

- [ ] 새 저장소만으로 노드와 모든 API route가 등록된다.
- [ ] Ollama/llama.cpp/prompt 코드나 런타임 dependency가 없다.
- [ ] 사용자 표시와 공개 식별자에 Director 명칭이 남지 않는다.
- [ ] 현재 IMAGE/AUDIO/VIDEO 출력 및 caption/manifest 계약이 보존된다.
- [ ] frontend와 backend 자동 테스트가 모두 통과한다.
- [ ] 실제 Nodes 2.0 및 Legacy Canvas smoke test를 통과한다.
- [ ] `bun run release:check`와 Registry ZIP 검사가 통과한다.
- [ ] 새 저장소의 `v0.1.0` tag와 Registry release를 만들 수 있다.
- [ ] 이후 기존 저장소에서 Reference Director 구현과 등록을 제거한다.
