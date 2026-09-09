# DATA:EZ 디자인 시안

OpenAI Platform의 사용자 제공 화면을 참고한 분석 작업 공간과 파일 보관함 시안이다. HTML을 브라우저에서 열거나 이 폴더만 로컬 HTTP 서버로 제공해 볼 수 있다. 원격 서비스에 배포하지 않았다.

- `index.html`: 중앙 결과, 오른쪽 접이식 채팅, 데이터 관리와 분석 기록 화면.
- `tokens.css`: 다크·라이트의 배경·텍스트·버튼·상태·차트 색상을 역할별로 관리하는 확정 차콜 + 블루 팔레트.
- `styles.css`: 공유 색상 토큰을 사용하는 화면 배치와 작은 화면 대응.
- `theme.js`: 다크 기본값, 다크·라이트·시스템 선택과 브라우저 설정 보관.
- `palette.html`, `palette.css`, `palette.js`: 두 테마를 나란히 비교하고 작업 공간에 적용하는 팔레트 화면.
- `palette-references.html`, `palette-references.css`, `palette-references.js`: 금융·매출 플랫폼 공식 레퍼런스와 블루·인디고·기존 민트 후보 비교. 다크/라이트·선/막대를 전환하며 기존 선택은 바꾸지 않는다. 출처와 관찰 범위는 `docs/PALETTE_REFERENCES.md`에 기록했다.
- `typography.html`, `typography.css`, `typography.js`: Pretendard·SUIT·Noto Sans KR·Wanted Sans·Spoqa Han Sans Neo를 같은 조건으로 비교하고 크기·굵기·간격·숫자 폭을 조절하는 화면.
- `fonts.css`, `fonts/`: 공식 배포처에서 받은 로컬 웹폰트, OFL 라이선스, 버전·출처·해시 기록.
- `type-settings.js`, `typography-preview.css`: 명시적으로 선택한 글꼴 설정을 디자인 작업 공간에 적용하고 보관하는 기능.
- `typography-verification.json`, `font-comparison.png`, `typography-dark.png`, `typography-light.png`, `typography-mobile.png`: 글꼴 검증과 렌더링 결과.
- `app.js`: 합성 데이터와 브라우저 내 시안 동작.
- `vendor/echarts-6.0.0.min.js`: 실제 Apache ECharts 6.0.0, SVG 렌더러. 외부 CDN 연결 없이 실행한다. 라이선스·NOTICE를 함께 보관한다.
- `workspace-chat.png`, `workspace-wide.png`, `file-library.png`, `mobile-workspace.png`: 실제 Edge 렌더링 화면.
- `verification.json`: 브라우저에서 확인한 시안 동작과 범위.
- `theme-verification.json`: 테마 상태 유지, 시스템 설정, 선택한 색상 쌍의 대비 검증.

## 확정한 디자인 기준

2026-09-09 확정: Spoqa Han Sans Neo + 차콜/블루. 2026-09-10 현재 실제 Next.js 앱에도 배치·색상·테마와 ECharts 6.1.0을 통합했다. 아래 초기 시안 동작은 실제 앱 캡처·통합 검증과 구분한다. 주요 계열은 블루, 비교 계열은 앰버, 취소는 로즈, 분석 가능 상태는 그린으로 표시한다.

## 체험할 수 있는 동작

1. 오른쪽 위 '분석 채팅'으로 패널을 접고 펼친다.
2. 선·막대 버튼으로 차트 종류를 바꾸고, 그래프에 마우스를 올려 금액을 확인한다.
3. 예시 질문 '현금만 보여줘', '카드만 보여줘', '전체를 선그래프로 보여줘'로 중앙 그래프를 바꾼다.
4. 집계표에서 선택한 그래프의 값과 계산 기준을 확인한다.
5. 데이터 관리에서 파일명 검색·형식 필터, CSV 미리보기·다운로드, '이 파일로 분석'을 체험한다.
6. 상단의 '화면 테마'에서 다크·라이트·시스템을 선택한다. 테마를 바꿔도 현재 분석은 유지된다.
7. 왼쪽 아래 '컬러 팔레트'에서 두 테마의 색상을 비교한다. 차콜 + 블루를 확정했으며 다크·라이트를 함께 제공한다.
8. '글꼴 비교실'에서 후보를 고르고 본문 크기·굵기·자간·행간·대표 금액 크기·숫자 폭을 조절한다. '이 설정으로 작업 공간 보기'는 현재 설정을 시안에 적용한다. JSON 저장·CSS 복사도 가능하다.

## 시안과 실제 서비스의 경계

이 폴더의 초기 `index.html` 시안 자체는 실제 LLM, 로그인, 장부 SQL, 원격 저장소에 연결하지 않았다. 실제 Next.js 앱은 후속 단계에서 ECharts로 전환했고 별도 실제 연동 검증을 완료했다. 채팅은 정해진 예시에 반응하고, 저장 상태는 새로고침 시 초기화한다. '새 분석'은 현재 샘플 분석을 여는 동작이다. 배치 드래그·리사이징은 이번 시안에 포함하지 않았다.

선택한 테마와 명시적으로 적용한 글꼴 설정을 브라우저 저장소에 보관한다. 저장된 설정이 없는 첫 방문은 다크로 시작한다. 글꼴 비교실과 작업 공간은 확정한 Spoqa Han Sans Neo로 시작하며 단순 비교는 저장하지 않는다. 이전 글꼴 설정은 Spoqa로 전환하고 크기·간격은 유지한다. 테마 상세는 [컬러 팔레트 설계](../../docs/COLOR_PALETTE.md), 글꼴 출처·숫자 정렬·비교 방법은 [글꼴 설계](../../docs/TYPOGRAPHY.md)에 기록한다. Spoqa 기본 글꼴, 새 배치와 테마는 실제 앱에도 적용했다.

파일 추가는 현재 화면의 목록에 파일 이름·형식·크기만 추가하며 내용을 업로드하지 않는다. 카드·현금 CSV 두 항목은 다운로드 가능한 합성 원본을 실제로 생성한다. 나머지 두 항목은 상태를 보여주는 예시다.

합성 데이터의 9월 1일–7일 총 결제액은 17,410,000원, 카드 취소금액은 610,000원, 순결제액은 16,800,000원이다. 그래프 종류·파일 필터 변경은 실제 시안 데이터에 적용한다. 상단 요약과 하단 보조 그래프는 전체 카드·현금 기준이며, 채팅에서 결제수단을 바꾸면 중앙 그래프만 변경한다.

## 그래프 엔진 검토

실제 앱은 2026-09-10 Phase 4에서 ECharts 6.1.0으로 전환했다. [실제 구현과 검증](../../docs/ANALYSIS_DASHBOARD_UI.md). 아래는 초기 엔진 비교 기록이다. Recharts도 축·라벨·툴팁·색상을 구성하면 현재 참고 화면과 같은 정돈된 그래프를 만들 수 있다. 시안에서는 차트 종류와 탐색 기능 확장을 고려해 ECharts를 후보로 사용했다. 실제 교체 시에는 기존 차트 유형, 음수·NULL·정밀 소수 표시, 가게 범위 및 저장 지표의 동일 결과를 확인해야 한다. 시안 통과는 기존 앱 전체 검증을 의미하지 않는다.

vgpu는 Vercel이 관리하는 WebGPU 그래픽 라이브러리다. 문서·예제·셰이더 검증 도구를 에이전트가 사용하기 쉽게 제공한다. DATA:EZ에서는 소개 화면이나 빈 작업 공간의 빛·입자·물결 효과 후보로 검토할 수 있다. 축·범례·단위·툴팁이 필요한 통계 차트에는 ECharts를 우선 추천한다. vgpu를 설치하거나 실행 검증하지 않았으며, 'agent-first'가 DATA:EZ의 자연어 분석·RAG를 제공한다는 뜻은 아니다.

참고한 공식 자료:

- [Recharts 예제](https://recharts.github.io/en-US/examples/)
- [ECharts 기능](https://echarts.apache.org/en/feature.html)
- [ECharts 스타일](https://echarts.apache.org/handbook/en/concepts/style/)
- [ECharts Canvas·SVG 선택](https://echarts.apache.org/handbook/en/best-practices/canvas-vs-svg/)
- [vgpu 소개](https://vgpu.sh/about)
- [vgpu 0.3.1 README](https://github.com/vercel-labs/vgpu/blob/v0.3.1/packages/vgpu-api/README.md)
- [vgpu 예제](https://vgpu.sh/examples)

## 실제 앱 공통 화면 통합 (2026-09-09)

[실제 앱 구현 화면](app-workspace.html)은 Next.js production build에 테스트 API 응답을 연결한 캡처 비교 화면이다. 기존 HTML 시안과 구분한다. [완료 범위와 검증](../../docs/WORKSPACE_FOUNDATION.md)을 참고한다.

## 분석 결과·대시보드 UI 통합 (2026-09-10)

[화면 비교](app-workspace.html?phase=analysis-dashboard)에 실제 앱의 분석 결과, 집계표·SQL, KPI·대시보드, 모바일 화면을 추가했다. 테스트 API로 실행한 캡처이며 실제 LLM 응답이나 매출이 아니다. [완료 범위와 검증](../../docs/ANALYSIS_DASHBOARD_UI.md).

## 최신 실제 연동 검증 (2026-09-10)

[integration-validation.html](integration-validation.html)은 실제 브라우저·API·DB·LLM을 연결한 최신 실행의 화면과 결과를 보여준다. 자연어 질문 6개·점검 29개이며 파일 원본과 누적 장부, 저장 전 설정, 샘플 가게의 첫 대시보드를 포함한다. [보고서](workspace-live/report.json), [실행 조건과 한계](../../docs/WORKSPACE_LIVE_ACCEPTANCE.md), [최신 사용 계약](../../docs/FILE_SCOPE_AND_FIRST_USE.md)을 함께 확인한다. 실제 PG 파일·원격 저장소 검증은 포함하지 않았다.
