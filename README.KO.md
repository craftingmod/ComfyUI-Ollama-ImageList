# ComfyUI llama multimodal

![썸네일](./docs/icon.svg)

[English](./README.md) | [한국어](./README.KO.md)

ComfyUI를 위한 LLM 및 멀티모달 노드입니다.

서로 다른 크기의 이미지와 비디오, 오디오를 `llama.cpp`를 통해 멀티모달 LLM에 전달하고, 모델 로딩과 생성 설정을 조절할 수 있습니다. `CLIP`과 `Ollama`도 일부 지원합니다.

동영상 프롬프트 작성, 미디어 설명, 번역 등에 사용하기 좋습니다.

## 지원 런타임

* `llama.cpp`: HTTP(S) 서버에 연결하거나 `PATH`에 있는 `llama` 실행 파일을 사용합니다.
* `CLIP`: 서로 다른 해상도의 미디어를 입력받는 ComfyUI CLIP 모델을 기본적으로 지원합니다.
* `Ollama`: 여러 이미지 입력을 기본적으로 지원합니다. 오디오와 비디오는 지원하지 않습니다.

`PATH`에 `llama`가 없다면 Settings → llama-multimodal → Download llama.cpp에서 다운로드할 수 있습니다.

로컬 GGUF 모델을 사용하려면 모델과 해당 모델에 맞는 멀티모달 프로젝터(`mmproj`)를 `ComfyUI/models/LLM`에 넣으세요.

이미지, 비디오, 오디오 지원 여부는 선택한 모델에 따라 다릅니다.

## 예제

![vision 예제](./workflows/llamacpp_vision.avif)

[workflow 다운로드](./workflows/llamacpp_vision.json)

vision LLM으로 여러 미디어 입력에서 텍스트를 생성하는 예제입니다.

더 많은 예제는 [EXAMPLES.md](./workflows/EXAMPLES.md)에서 확인할 수 있습니다.

## 설치

ComfyUI 0.19.3 이상이 필요합니다.

* ComfyUI Manager

`llama multimodal`을 검색해 `llama-multimodal`을 설치하세요.

* Comfy CLI

```sh
comfy node install ollama-image-list
```

* 수동 설치

```sh
cd ComfyUI/custom_nodes
git clone https://github.com/craftingmod/ComfyUI-Ollama-ImageList.git
```

## 개발

수동 설치 안내에 따라 저장소를 복제한 뒤, 저장소 디렉터리에서 다음 명령을 실행하세요.

```sh
uv venv .venv
./.venv/Scripts/Activate
uv sync
bun install
```

이어서 frontend를 빌드하세요.

```sh
bun run build
```

다른 스크립트는 [package.json](./package.json)에서 확인할 수 있습니다.
