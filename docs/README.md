# DATA:EZ 문서

2026-09-10 기준. 제품 방향은 [PRD](PRD.md), 최신 사용자 동작은 [분석 범위·저장 설정·첫 사용 안내](FILE_SCOPE_AND_FIRST_USE.md)를 우선한다. 각 Phase 문서는 해당 단계의 설계와 검증 기록이며 이후 변경이 반영된 문서를 함께 연결한다.

## 처음 읽을 문서

| 목적 | 문서 |
|---|---|
| 서비스 개요·실행·현재 검증 | [프로젝트 README](../README.md) |
| 사용자와 제품 범위·후속 과제 | [PRD](PRD.md) |
| 원본과 누적 장부·저장 설정·샘플 | [최신 사용 흐름](FILE_SCOPE_AND_FIRST_USE.md) |
| 코드 구조와 계산·검색·저장 경계 | [아키텍처](ARCHITECTURE.md) |
| 개발 환경·테스트 실행 | [기여·개발 안내](../CONTRIBUTING.md) |
| 환경변수·마이그레이션·운영 | [설정](CONFIGURATION.md), [실행·배포](DEPLOYMENT.md) |
| 이번 통합의 브랜치·PR·검증 | [머지 기록](RELEASE_INTEGRATION.md) |

## 구현별 문서

| 영역 | 문서 |
|---|---|
| 가져오기와 데이터 신뢰성 | [기반 검사 A](IMPORT_FOUNDATION.md), [출처별 반복 반영 B](LEDGER_IMPORTS.md), [이벤트 검토 C](EVENT_REVIEW.md) |
| 결제 속성·복원 | [수단·채널·수수료 G](PAYMENT_ATTRIBUTES.md), [기존 자료 속성 복원 H](ATTRIBUTE_RESTORATION.md) |
| 지표와 현금 | [지표 기반](METRIC_IMPLEMENTATION.md), [계산식·이력·현금 K·L](METRICS_AND_CASH.md), [그룹 계산식](FORMULA_CHARTS.md), [여러 가게 M](MULTI_STORE_METRICS.md) |
| 검색과 파일 | [검색 색인·복구 I](SEARCH_INDEX_JOBS.md), [파일 보관함·채팅](FILE_LIBRARY_CHAT.md), [최신 원본 범위](FILE_SCOPE_AND_FIRST_USE.md) |
| 화면과 첫 사용 | [작업 공간](WORKSPACE_FOUNDATION.md), [ECharts·대시보드](ANALYSIS_DASHBOARD_UI.md), [파일 매핑부터 첫 지표 J](FIRST_DASHBOARD.md) |

## 검증 근거

| 범위 | 설명·실행 방법 |
|---|---|
| 최신 실제 브라우저·API·DB·LLM | [6개 질문·29개 점검](WORKSPACE_LIVE_ACCEPTANCE.md), [결과 JSON](../outputs/frontend-design/workspace-live/report.json), [화면 모음](../outputs/frontend-design/integration-validation.html) |
| 최신 파일·저장·샘플 회귀 | [API·브라우저 검증 범위](FILE_SCOPE_AND_FIRST_USE.md#검증) |
| 자연어 50문항 N | [전체 47/50 및 후속 10/10](NATURAL_LANGUAGE_ACCEPTANCE.md), [평가 실행 도구](../scripts/nl-eval/README.md) |
| 합성 PG 데이터 E | [평가 기록](PG_SAMPLE_EVALUATION.md), [CSV·엑셀 사용 순서](../samples/pg-evaluation/README.md) |
| 실제 검색 F | [RAG 평가](RAG_ACCEPTANCE.md) |
| 초기 매출 반영·스케줄러 D | [통합 검증 기록](INTEGRATED_ACCEPTANCE.md) |
| 단계별 원시 근거 | [JSON 보고서·화면](evaluations/) |

fixture 기반 UI 검사, 실제 DB 검사, 실제 LLM 검사는 서로 다른 범위다. 최신 결과를 이전 성적에 합산하지 않으며, 건너뛴 검사는 실행된 것으로 보고하지 않는다. 실제 PG 파일·원격 저장소·운영 부하는 별도 검증이다.

## 디자인 결정과 기록

- [글꼴](TYPOGRAPHY.md): Spoqa Han Sans Neo 확정, 후보·출처·숫자 정렬.
- [컬러 팔레트](COLOR_PALETTE.md), [레퍼런스 비교](PALETTE_REFERENCES.md): Charcoal + Blue, 다크 기본·라이트 지원.
- [프론트엔드 재설계](FRONTEND_REDESIGN.md): 메뉴·접이식 채팅·파일 보관함의 합의와 단계별 진행.
- [HTML 비교·시연 폴더](../outputs/frontend-design/README.md): 초기 정적 시안과 실제 앱 캡처를 구분.
- [초기 엔지니어링 기록](ENGINEERING_HISTORY.md): 관측성·라우터·한국어 검색 개선 당시 수치.
- [초기 에이전트 제안](AGENT_ADVANCEMENT_PLAN.md), [데이터 신뢰성 계획](NEXT_PHASE_DATA_RELIABILITY.md): 과거 계획. 현재 제품 범위는 PRD와 후속 구현 문서를 따른다.
