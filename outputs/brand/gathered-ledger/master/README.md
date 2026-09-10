# DATA:EZ 로고·아이콘 마스터 패키지

버전 1.0 · 2026-09-11 · BI 방향 **Gathered Ledger**

## 빠른 선택

| 사용 환경 | 권장 파일 |
|---|---|
| 다크 UI | `vector/dataez-lockup-dark.svg` |
| 라이트 UI | `vector/dataez-lockup-light.svg` |
| 작은 UI 아이콘 | `vector/dataez-symbol-blue.svg` 또는 `raster/dataez-symbol-blue-{size}.png` |
| 앱 아이콘·프로필 이미지 | `vector/dataez-app-icon-blue.svg` 또는 대응 PNG |
| 흑백 인쇄 | `vector/dataez-lockup-black.svg` / `dataez-lockup-white.svg` |

SVG를 우선 사용하고, SVG를 지원하지 않거나 정확한 픽셀 크기가 필요한 곳에서 PNG를 사용한다.

## 폴더 구성

- `vector/`: 다크·라이트·흑백 가로 로고, 블루·밝은 블루·흑백 독립 심볼, 블루·차콜 앱 아이콘
- `raster/`: 16–512px 독립 심볼과 앱 아이콘, 1280×256 투명 배경 가로 로고

앱 아이콘 PNG는 `16`, `32`, `48`, `180`, `192`, `512px`로 제공한다. 블루 심볼 PNG는 `16`, `24`, `32`, `64`, `128`, `256`, `512px`로 제공한다.

## 재생성 및 검증

저장소 루트에서 `npm ci --prefix scripts/ui-eval`로 검증 도구를 설치한 뒤
`pwsh -File scripts/brand/export-master-assets.ps1`을 실행한다. Chrome이 필요하며
다른 설치 경로는 `-ChromePath`로 지정할 수 있다.

SVG를 정확한 픽셀 크기의 브라우저 viewport에 렌더링하고, PNG 28개의 크기·투명
배경·빈 이미지·잘림 여부를 확인한 뒤 `dataez-brand-master-v1.zip`을 갱신한다.
Windows Chrome CLI의 최소 창 너비 때문에 발생하던 소형 자산 잘림을 수정했다.
로고 형태와 색상은 기존 SVG 원본을 그대로 사용한다.

## 사용 규칙

- 심볼 사방에 최소 획 두께 1배, 가로 로고 사방에 최소 획 두께 1.5배의 보호 여백을 둔다.
- 독립 심볼은 디지털 16px, 가로 로고는 디지털 너비 120px보다 작게 사용하지 않는다.
- 심볼과 워드마크의 비율·간격·색을 임의로 바꾸지 않는다.
- 효과, 그림자, 외곽선, 임의의 그라디언트를 추가하지 않는다.
- 다크 UI에서는 Bright Blue `#82B4FF`와 Cloud White `#F2F4F7`, 라이트 UI에서는 Trust Blue `#245BB5`와 Ink `#20262F` 조합을 유지한다.

상표 등록이나 대규모 매체 집행 전에는 별도의 상표 유사성·인쇄 감리 검토를 권장한다.
