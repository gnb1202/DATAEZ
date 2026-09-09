# DATA:EZ 금융·매출 플랫폼 팔레트 리서치

확인일: 2026-09-09. 비교 후 사용자가 A안인 차콜 + 블루를 최종 확정했다. 공통 디자인 시안에 반영했으며 실제 Next.js 앱의 색상 통합은 다음 페이즈다. 확정 토큰과 검증 결과는 [COLOR_PALETTE.md](COLOR_PALETTE.md)를 기준으로 한다.

## 확인 범위

공식 문서, 공식 홍보 페이지에 포함된 제품 예시, Mercury의 공개 데모를 확인했다. 로그인한 고객 계정은 사용하지 않았다. 토스 TDS만 공식 문서의 HEX를 인용하고, 다른 서비스의 색감은 화면 관찰로 기록한다. 아래 후보의 HEX는 DATA:EZ용 제안 값이다. 특히 Square 홍보 페이지에는 과거 화면 예시가 포함되어 있어 최신 제품 UI로 간주하지 않는다.

| 레퍼런스 | 확인한 내용 | DATA:EZ에 참고할 부분 |
| --- | --- | --- |
| [토스 TDS Colors](https://tossmini-docs.toss.im/tds-mobile/foundation/colors/) | 공식 blue500 #3182F6, grey50 #F9FAFB, grey900 #191F28. 회색·강조·상태의 색상 단계 | 버튼과 선택 상태의 강조색, 텍스트 계층 |
| [Mercury 공개 데모](https://demo.mercury.com/dashboard) | 다크 화면의 잉크색 바탕, 인디고 버튼·잔액 그래프, 패널 간 밝기 구분 | 다크 대시보드의 배경 층위, 큰 금액은 기본 텍스트색으로 표시 |
| [Mercury 테마 안내](https://support.mercury.com/hc/en-us/articles/37538153196948-Enabling-dark-mode) | 웹·모바일 다크/라이트/시스템 설정 지원 | 테마를 동등한 범위로 설계 |
| [Mercury 2022 설계 글](https://mercury.com/blog/december-2022-product-updates) | 색 이름 중심에서 용도별 의미를 가진 토큰으로 전환한 설명 | 배경·텍스트·상태 등 역할별 토큰 |
| [Stripe Sigma](https://stripe.com/en-de/sigma) | 공개 차트 예시의 흰색·회색 작업 화면, 보라·블루·청록 계열. 자연어/SQL 보고서와 차트·대시보드 연결 | DATA:EZ의 분석 흐름, 화면 강조색과 데이터 계열 색상 구분 |
| [캐시노트](https://info.cashnote.kr/main) | 공개 장부 이미지의 합계·결제수단별 금액·실적 캘린더, 밝은 화면과 블루 계열 | 소상공인이 읽을 정보 순서 |
| [Square 분석 소개](https://squareup.com/us/en/point-of-sale/features/dashboard/analytics) / [보고서 안내](https://squareup.com/help/us/en/article/5381-in-app-summaries-and-reports) | 공개 예시의 블루 차트와 표. 보고서의 가게·기간·결제수단·지표 정의·선/막대 전환 | 다점포 범위와 계산 기준 노출, 그래프와 원자료 함께 제공 |

## 비교와 확정

- A. 차콜 + 블루: 사용자 확정. 현재 화면의 중립적인 다크 바탕을 유지하고, 실행·선택 색을 성공 상태의 그린과 구분한다. 특정 색이 사용자 신뢰나 사용성을 보장한다는 연구 결과로 제시하는 것은 아니며 DATA:EZ의 화면 역할에 근거한 디자인 판단이다.
- B. 잉크 + 인디고: Mercury의 다크 화면에서 영감을 받은 대안. 보라색 면적을 핵심 행동과 그래프에 제한한다.
- C. 차콜 + 민트: 이전 팔레트를 비교 기록으로 남긴다. 강조와 성공의 색감이 비슷하므로 상태 라벨과 형태도 함께 사용한다.

각 후보의 다크/라이트 HEX는 `outputs/frontend-design/palette-references.js`에 있다. 글꼴·숫자·구조는 동일하며 테마와 선/막대만 전환한다. 후보는 localStorage나 기존 `tokens.css`를 변경하지 않는다. ECharts 6.0.0 로컬 SVG 렌더러와 기존 Spoqa 자산을 재사용한다.

순결제 16,800,000원 = 결제 17,410,000원 − 취소 610,000원. 기존 작업 공간과 동일한 9월 1–7일 합성 수치를 사용한다. 취소는 집계 데이터로 표시하며 처리 오류와는 별도 의미를 갖는다. 확정 색상의 시안 대비를 검증했다. 실제 앱 통합 때 여러 가게·여러 데이터 계열의 구분과 전체 상태를 추가 검증한다.

비교 페이지: `http://127.0.0.1:3131/palette-references.html`
