# DATA:EZ 글꼴 — Spoqa Han Sans Neo 확정

2026-09-09. 금융·매출 데이터에서 금액과 한글을 함께 읽기 좋은 글꼴을 사용자가 직접 선택할 수 있도록 [HTML 글꼴 비교실](../outputs/frontend-design/typography.html)을 만들었다. 다크를 기본으로 하고 기존 색상 토큰과 라이트·시스템 선택을 공유한다. 사용자가 Spoqa Han Sans Neo로 확정했으며, 실제 앱과 디자인 시안의 기본 글꼴에 적용했다.

## 확정 결과와 비교 후보

| 후보 | 이 시안에서의 디자인 판단 | 비교용 파일 |
|---|---|---|
| A · Pretendard | 균형 있는 인상으로 비교했던 후보 | v1.3.9 variable WOFF2 |
| B · SUIT | 단정하고 가벼운 인상, 여백이 있는 화면의 대안 | v2.0.5 variable WOFF2 |
| C · Noto Sans KR | 익숙하고 견고한 인상, 확정 글꼴의 한글 폴백 | Google Fonts 저장소의 고정 커밋 |
| D · Wanted Sans | 곧고 또렷한 인상, 서비스 개성을 위한 추가 후보 | v1.0.3 variable WOFF2 |
| **E · Spoqa Han Sans Neo · 확정** | 본문·강조·금액에 사용하는 기본 글꼴 | v3.3.0 WOFF2, 400·500·700 |

실제 앱은 `web/app/layout.tsx`에서 로컬 Spoqa Han Sans Neo 400·500·700을 로드한다. 일반 UI와 금액은 Spoqa, 지원하지 않는 한글은 로컬 Noto Sans KR, 코드·SQL·JSON은 JetBrains Mono를 사용한다. 금액 카드, 지표 집계표와 차트 툴팁의 고정폭 코드 글꼴 지정도 Spoqa와 숫자 정렬 설정으로 바꿨다.

기존 Tailwind `font-semibold`는 제공되는 Bold 700에 매핑했다. 글꼴·굵기와 금액 표시만 앱에 반영했으며, 새 화면 배치·색상·ECharts 전환은 별도 범위다.

시안 기본값: 본문 15px / 400, 본문 자간 −0.015em, 행간 1.7, 강조 500, 제목 700, 대표 금액 32px / 700. 실제 앱의 기존 글자 크기 체계는 유지한다. 대표 금액은 작은 화면에서 영역 안에 들어오도록 축소한다. 본문 전체를 고정폭 글꼴로 구성하지 않고, 금액에 숫자 폭 고정과 우측 정렬을 적용한다.

## 비교와 조절

- 위의 다섯 카드는 글꼴만 달리하고 크기·굵기·간격을 동일하게 유지한다. 모든 후보가 실제로 제공하는 본문 400, 카드 제목·금액 500을 공통 비교 기준으로 사용한다. 아래 미리보기는 선택한 글꼴과 조절값을 적용한다.
- 본문 크기 13–18px, 굵기 400–600(가변 글꼴) 또는 400·500·700(Spoqa), 자간 −0.04–0.01em, 행간 1.4–1.9, 대표 금액 26–40px을 조절한다.
- 금액 카드, 실제 ECharts 차트의 축·툴팁, 결제표, 채팅 문장, 숫자·통화·음수·퍼센트 예시를 제공한다.
- 직접 입력한 문장은 `textContent`로 표시한다. 웹으로 전송하거나 저장하지 않는다.
- '이 설정으로 작업 공간 보기'를 누르면 기존 디자인 시안의 글꼴·본문 밀도·대표 금액에 적용하고 브라우저에 보관한다. 이 조절값은 시안에만 보관하며 실제 앱의 설정·DB·LLM에는 전송하지 않는다. 앱의 기본 글꼴 선택은 코드에 별도로 반영했다.
- JSON 다운로드와 CSS 복사를 제공한다. 클립보드 사용이 거부되면 선택 가능한 CSS를 펼친다.
- 초기화는 확정한 Spoqa 기본 설정으로 복원한다. 이전에 적용한 설정을 덮어쓰려면 적용 버튼을 다시 누른다.

저장 키는 `dataez-design-typography-v2`이다. 기존 v1 설정은 글꼴만 Spoqa로 전환하고 크기·간격은 유지한다. 굵기는 가까운 지원 값으로 맞추며, 숫자 폭은 기본 고정폭을 사용한다. 새 설정을 저장하지 않아도 처음부터 Spoqa로 표시한다. 단순 비교·조절은 저장하지 않는다. 브라우저 저장소를 사용할 수 없으면 URL의 검증된 설정으로 작업 공간에 전달한다. 테마는 기존 `dataez-design-theme`를 사용한다.

## 숫자와 글리프

Pretendard·SUIT·Wanted Sans는 `tnum`·`pnum`을 제공한다. SUIT는 커닝이 켜져 있으면 `1,111,111원`과 `8,888,888원`의 폭이 달라질 수 있어 금액에는 `font-kerning: none`도 적용했다. 금액의 자간은 0으로 유지한다.

이 Noto Sans KR와 Spoqa Han Sans Neo 파일은 숫자 0–9의 기본 폭이 동일하며 `tnum`·`pnum` 기능은 없다. 선택 시 숫자 너비 조절을 비활성화하고 기본 폭이 같다고 설명한다. 차트의 SVG 글자에도 숫자 설정을 적용한다.

파일의 cmap 검사에서 Pretendard·Noto Sans KR·Wanted Sans는 현대 한글 완성형 11,172자를, SUIT WOFF2는 2,668자, Spoqa WOFF2는 2,574자를 포함했다. SUIT·Spoqa에 없는 한글은 로컬 Noto Sans KR로 폴백한다. 후보 카드의 샘플은 각 후보의 실제 웹폰트 글리프로 렌더링되는 것을 Edge에서 확인했다.

Spoqa는 본문 굵기 슬라이더를 실제 지원하는 400·500·700 세 단계로 표시한다. 미리보기 제목·대표 금액은 실제 Bold 700을 사용하고, CSS 내보내기에도 이를 반영한다. 다른 후보의 미리보기 제목·대표 금액 기본값은 600이다.

## 파일과 출처

모든 비교용 글꼴은 `outputs/frontend-design/fonts`에 로컬로 포함하고 각 원본의 SIL Open Font License 1.1을 함께 보관한다. 외부 CDN 요청 없이 비교한다.

- [Pretendard 공식 저장소](https://github.com/orioncactus/pretendard), [고정 버전 CSS](https://github.com/orioncactus/pretendard/blob/v1.3.9/packages/pretendard/dist/web/variable/pretendardvariable.css)
- [SUIT 공식 저장소](https://github.com/sun-typeface/SUIT), [고정 버전 글꼴](https://github.com/sun-typeface/SUIT/tree/v2.0.5/fonts/variable/woff2)
- [Noto Sans KR · Google Fonts](https://github.com/google/fonts/tree/b38c5c93af322c45f633e17ac440ec1e6c94d489/ofl/notosanskr)
- [Wanted Sans 고정 버전](https://github.com/wanteddev/wanted-sans/tree/v1.0.3), OFL·AUTHORS 포함
- [Spoqa Han Sans Neo 고정 버전](https://github.com/spoqa/spoqa-han-sans/tree/v3.3.0/Subset/SpoqaHanSansNeo), OFL·LICENSE 포함
- [파일 출처·버전·해시·글리프·기능 기록](../outputs/frontend-design/fonts/manifest.json)

Pretendard 2,057,688바이트, SUIT 624,536바이트, Noto Sans KR 3,908,496바이트, Wanted Sans 1,289,292바이트, Spoqa 3개 굵기 합계 544,268바이트. Noto 원본 TTF는 fontTools로 WOFF2 포장만 바꾸었으며 글리프 편집이나 서브셋을 하지 않았다. 앱에는 Spoqa 3개 파일과 Noto 폴백을 `next/font/local`로 연결했고, 폴백은 미리 로드하지 않는다. 원본 라이선스·해시·출처 기록은 `web/public/font-licenses`에도 포함한다.

## 검증

[브라우저 검증 기록](../outputs/frontend-design/typography-verification.json): Spoqa 확정 후 Edge에서 22개 검증 그룹 통과. 실제 사용 글리프를 CDP로 확인했고, 숫자 폭, 다섯 조절값, 테마 변경 시 데이터 유지, JSON 내용, 클립보드 거부 대응, 시안 적용·재접속, 저장소 차단 시 URL 전달, 각 글꼴의 최대 크기에서 1480·1280·1100·820·390·320px 화면을 확인했다. 추가 두 후보의 설정 내보내기·작업 공간 적용·재접속과 Spoqa의 실제 굵기 선택도 확인했다. 좁은 화면의 표는 별도 영역 안에서 스크롤한다.

기존 시안 동작 15개와 테마 검증 16개도 통과했다. 다크·라이트·모바일 화면을 실제 렌더링해 확인했다. 이 기록은 디자인 시안 검증이며 실제 앱 전체의 접근성·사용성 검증은 아니다.

실제 Next.js 앱은 `npm run build`(타입 검사 포함)를 통과했다. 빌드 결과를 로컬에서 실행하여 로그인 화면의 실제 Spoqa Bold 글리프와 400·500·700 웹폰트 로딩, 화면 넘침 없음, 브라우저 오류 없음을 확인했다. `spoqa-app-login.png`는 해당 화면이다. 인증된 실제 계정의 데이터 흐름까지 재검증한 것은 아니다.

ESLint는 기존 `.eslintrc.json`과 설치된 ESLint 9 / Next 설정 형식 불일치로 실행되지 않았다. 기본 실행은 flat config 누락, legacy 모드는 Next 설정의 순환 참조 오류를 반환했다. 글꼴 변경과 별개인 lint 설정 정리는 후속 작업이다.

2026-09-09 후속: 공통 작업 공간 페이즈에서 ESLint 9 flat config로 전환했다. 현재 lint 실행이 가능하며 기존 폼의 React Compiler 진단 등 남아 있는 경고는 [공통 화면 검증](WORKSPACE_FOUNDATION.md)에 기록한다.
