# DATA:EZ 포트폴리오 영상 · Phase 3

2026-09-12 촬영. **실제 공개 서비스 녹화 + 무음 한국어 자막**으로 만든 로컬 영상 패키지다. Git에는 제작 도구·자막·검증 기록·대표 스크린샷을 보관하며, 영상 마스터는 `output/portfolio-demo/`에 있다. 영상 파일을 공개 호스팅에 올리지는 않았다.

## 재생

로컬 미리보기: [영상 3종 재생·다운로드](http://127.0.0.1:3134/). 서버를 종료했다면 저장소 루트에서 실행한다.

Phase 5에서 `output/portfolio-demo-delivery.zip` 전달 패키지를 만들고 새 임시 폴더에서 전체 재생했다. [최종 QA와 압축 해제 후 재생 안내](FINAL_QA.md#영상-전달-패키지)를 참고한다. 이 ZIP 역시 로컬 파일이며 Git 복제에 포함되지 않는다.

```powershell
python -m http.server 3134 --bind 127.0.0.1 --directory output/portfolio-demo
```

| 파일 | 길이 | 코덱 | 크기 |
|---|---:|---|---:|
| `product.mp4` | 110초 | h264 | 4.13 MiB |
| `technical.mp4` | 300초 | h264 | 10.55 MiB |
| `loop.mp4` | 12초 | h264 | 0.64 MiB |
| `loop.webm` | 12초 | vp9 | 0.50 MiB |

모든 출력은 1920×1080, 30fps, 무음이다. 제품·기술 MP4는 H.264/yuv420p/faststart, 반복 WebM은 VP9다. 원본 브라우저 녹화는 VP8 **25fps**이므로 30fps 출력은 프레임률 변환이며 새로운 동작 프레임을 생성한 것이 아니다.

- [제품 SRT](product.ko.srt), [기술 SRT](technical.ko.srt), [반복 SRT](loop.ko.srt): 영상에 입힌 동일한 한국어 자막.
- [완성 화면](assets/phase-3-product-3.png), [확대한 집계표·SQL](assets/phase-3-product-55.png), [저장 설정](assets/phase-3-product-66.png).
- [배포 구조 HTML](architecture.html), [구조도 검증 영수증](architecture-receipt.json).

## 촬영과 편집의 근거

- [촬영 기록](phase-3-capture.json): 동일한 가게·원본 파일에서 Q1과 Q2를 실제 전송했다. 응답 시간은 각각 11.11초 / 9.84초였다. 모델/API mock 없음, 브라우저 오류 0건.
- 원본은 690,200원, 거래 30,000원 1회 추가 후 누적 장부는 720,200원이다. 원본 파일 바이트 해시와 각 일별 값을 확인했다. 두 그래프 모두 전체 기간·KRW·수동 갱신으로 저장했다.
- 위젯 크기를 6열에서 12열로 실제 조절하고 재접속으로 보존을 확인했다. 두 번째 지표 저장 후 다시 6열로 줄이고 실제 드래그해 두 그래프를 나란히 배치했다. 예시 가게 전환과 복귀도 같은 녹화 안에 있다.
- 로그인은 녹화하지 않는 별도 브라우저 컨텍스트에서 완료했다. 촬영 컨텍스트는 인증 상태만 메모리에서 이어받으며, 계정 표시만 CSS로 숨긴다. 파란 커서 표시를 추가한다. 데이터·응답·그래프·성공 상태는 바꾸지 않는다.
- [편집 결정과 해시](phase-3-render.json): 원본은 167.16초다. 장면 재배열, 읽기 위한 마지막 프레임 유지, 집계표·SQL 확대, 일부 조작 구간 최대 약 1.05배 속도 조정이 있다. 질문 전송에서 완료까지의 모델 대기를 자르거나 12초 반복 영상 길이를 실제 응답 속도로 주장하지 않는다. 반복 영상 자체는 질문·결과·저장의 발췌본이다.
- 원본/누적 합계는 집계표 합계다. UI에 없는 KPI나 PG 자동 수집 장면을 합성하지 않았다. 기술 영상의 구조 카드와 API 거래 추가 설명은 실제 조작 화면과 구분한다.
- 실제 파일 선택 경로는 `library_references`와 `preview_metric`을 사용했다. RAG 검색 도구 호출을 촬영한 것으로 설명하지 않는다.

## 검수

[전체 프레임 디코딩·검은 화면 검사](phase-3-decode.json), [정상 속도 브라우저 전체 재생](phase-3-playback.json), [미리보기 반응형 검사](phase-3-preview.json)를 별도로 남긴다. 32개 시점의 프레임과 장면별 모음, 확대된 숫자·SQL·자막을 육안 확인했다. 전체 재생 검사는 세 영상을 각각 처음부터 끝까지 1배속으로 재생해 종료를 확인했다. 재생 정체는 0건이었다. 동시 재생에서 제품 영상은 3,300프레임 중 3프레임이 브라우저 표시에서 누락됐고, 기술·반복 영상은 0프레임이었다. 파일의 전체 프레임 디코딩 검사는 모두 통과했다.

집계표의 금액은 읽을 수 있도록 확대했다. SQL은 앱이 제공하는 가로 스크롤 영역의 집계·날짜 처리 부분을 보여주며, SQL 전체 텍스트를 한 화면에 표시했다고 주장하지 않는다. 파일 미리보기는 원본 앞부분이며 음수 취소 포함 여부는 실제 데이터·집계 검증 기록으로 확인한다.

구조도는 Archify의 9개 showcase 검사, 오류 0·경고 0을 통과했고 라이트·다크 실제 렌더링을 확인했다. 소스 근거는 `web/app/lib/direct-upload.ts`, `api/app/direct_uploads.py`, `api/app/dashboard_metrics.py`, `api/app/rate_limiter.py`, `api/app/maintenance.py`, `api/app/config.py`다. 구조도는 동작 설명이며 모든 연결을 촬영 중 실행한 증거가 아니다.

## 다시 제작하기

필요 도구: Python + httpx + fontTools/brotli, Node.js, `scripts/ui-eval`의 Playwright와 Edge, FFmpeg/ffprobe. Spoqa 폰트는 저장소의 WOFF2를 로컬 TTF로 패키징하며 원래 저작권·라이선스도 미리보기 폴더에 복사한다.

```powershell
# 이미 사용한 촬영 가게라면 새 가게를 만들며 이전 자료는 보존
python scripts/portfolio-demo/rehearse.py --record --new-take
node scripts/portfolio-demo/video-assets.cjs
python scripts/portfolio-demo/render-video.py
node scripts/portfolio-demo/video-preview.cjs
# 미리보기 서버를 실행한 뒤 전체 재생 검사
node scripts/portfolio-demo/video-playback.cjs
```

캐시는 입력 파일 해시·시간 범위·화면 확대 조건을 대조한다. `--reuse-parts`는 **같은 원본·편집 범위**에서 자막·일부 새 컷을 조정할 때만 사용한다. 새 촬영본은 기본 렌더로 모든 컷을 다시 만든다. 실패한 촬영에는 append를 자동 재전송하지 않고 새 take를 사용한다. 미완료 촬영은 렌더 도구가 거절한다.

Phase 4에서 [사례 문서](CASE_STUDY.md)와 [프로젝트 README](../../README.md)에 근거를 연결했고, Phase 5 [최종 QA](FINAL_QA.md)를 완료했다. 영상 공개 호스팅은 아직 남아 있다. 실제 PG 연동, 고객 사용성, 대규모 부하는 별도 과제다.
