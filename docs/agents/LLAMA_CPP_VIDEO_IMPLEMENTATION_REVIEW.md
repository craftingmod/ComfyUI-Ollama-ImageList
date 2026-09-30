# llama.cpp VIDEO MTMD 구현 검토 및 수정 항목

기준 문서는 JamePeng `llama-cpp-python`의 [Loading a Local Video With Generic MTMD](https://github.com/JamePeng/llama-cpp-python/blob/main/README.md#loading-a-local-video-with-generic-mtmd) 절이다.

## 판정

현재 구현은 VIDEO 입력의 정규화와 메시지 payload 전달까지는 구현되어 있다. 그러나 현재 JamePeng API와의 명시적 Generic handler 생성 계약이 맞지 않으며, 실제 `MTMD_VIDEO` 프레임 디코드까지 자동 테스트되지 않는다. 따라서 완전한 VIDEO MTMD 구현으로 판정할 수 없다.

FFmpeg가 시스템에 설치되어 있고 PATH에서 실행 가능하다는 전제는 이 문서의 수정 범위에서 제외한다. `video_ffmpeg_bin_dir` 입력을 추가하는 작업도 이번 범위에는 포함하지 않는다.

## 수정 필요 항목

### 1. 명시적 `handler="generic"` 생성 시 `chat_format=None` 전달

우선순위: P1

현재 [`backend/backends/llama_cpp.py:661`](../backend/backends/llama_cpp.py:661)의 `_create_handler()`는 `custom_chat_template`이 비어 있을 때 `chat_format`을 전달하지 않는다.

현재 포크의 `GenericMTMDChatHandler` 생성자는 `chat_format`을 필수 인자로 받는다. 따라서 다음 경로가 실패할 수 있다.

```text
VIDEO 입력
  -> handler="generic"
  -> GenericMTMDChatHandler(mmproj_path=..., verbose=...)
  -> missing required argument: chat_format
```

수정 방향:

```python
if handler == "generic":
    handler_kwargs["chat_format"] = custom_chat_template or None
```

`None`을 전달하면 handler가 모델의 `tokenizer.chat_template`을 실행 시점에 해석할 수 있다. 커스텀 템플릿이 있으면 기존처럼 그 값을 우선 사용한다.

### 2. Generic handler 생성 테스트를 실제 생성자 계약으로 교체

현재 [`tests/backend/test_llama_cpp_backend.py:1205`](../tests/backend/test_llama_cpp_backend.py:1205)의 비디오 테스트는 `**kwargs`를 받는 `FakeVideoHandler`를 사용한다. 이 fake는 `chat_format` 누락을 검출하지 못한다.

다음 조건을 요구하는 fake를 추가해야 한다.

- `chat_format` keyword가 반드시 존재할 것
- 기본 Generic 경로에서는 값이 `None`일 것
- 커스텀 템플릿 경로에서는 전달한 문자열과 동일할 것
- `mmproj_path`와 `verbose`가 기존대로 전달될 것

이 테스트는 native decode를 대체하지 않으며, Python binding 경계의 회귀만 검출한다.

### 3. 실제 `MTMD_VIDEO` end-to-end 검증 추가

현재 자동 테스트는 실제 GGUF, mmproj, JamePeng wheel, `MTMD_VIDEO` native library, ComfyUI `VIDEO` 객체를 사용하지 않는다. [`docs/TESTING.md:40`](../docs/TESTING.md:40)도 이 범위를 수동 검증으로 명시하고 있다.

최소 수동 검증 항목:

1. `MTMD_VIDEO`로 빌드된 JamePeng wheel을 ComfyUI가 실제 사용하는 Python 환경에 설치한다.
2. vision-capable mmproj와 호환되는 비디오 모델을 선택한다.
3. 짧은 MP4를 `VIDEO` 입력에 연결하고 `handler="auto"`로 실행한다.
4. 같은 파일을 `handler="generic"`으로도 실행한다.
5. `verbose=True`에서 Generic handler 초기화, FFmpeg 기반 frame sampling, MTMD tokenization 로그를 확인한다.
6. Media Diagnostics에서 다음을 확인한다.

   - `capabilities.video == true`
   - `requested.video_count == 1`
   - `evaluated.video_count == 1`
   - `mtmd.all_media_evaluated == true`
   - 정상 completion 및 `metrics_json.model_unloaded == true`

이 검증은 프레임 디코드와 marker/count 처리를 확인하지만, 모델의 비디오 이해 품질까지 보증하지는 않는다.

## 수정하지 않아도 되는 현재 코드

- [`backend/core/normalize.py:400`](../backend/core/normalize.py:400)의 `normalize_video()`가 원본 encoded stream을 보존하는 동작
- [`backend/backends/llama_cpp.py:596`](../backend/backends/llama_cpp.py:596)의 `{"type": "video", "video": {"url": ...}}` payload
- `video_with_audio`를 별도 AUDIO 입력으로 처리하는 opt-in 동작
- VIDEO를 IMAGE frame batch로 변환하지 않는 구조

현재 payload는 Generic MTMD의 `video` schema와 맞으므로, VIDEO를 이미지 프레임 목록으로 바꾸는 수정은 필요하지 않다.

## 현재 검증 결과

`bun run test` 결과:

- Frontend: 16 passed
- Backend: 116 passed
- 전체 종료 코드: 0

단, 이 결과는 fake handler와 정규화 테스트를 포함한 저장소 회귀 검증이며 실제 native `MTMD_VIDEO` 실행 성공을 의미하지 않는다.

