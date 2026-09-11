# DATA:EZ 문서

2026-09-11 기준. 제품 방향은 [PRD](PRD.md), 최신 사용자 동작은 [분석 범위·저장 설정·첫 사용 안내](FILE_SCOPE_AND_FIRST_USE.md)를 우선한다. 각 Phase 문서는 해당 단계의 설계와 검증 기록이며 이후 변경이 반영된 문서를 함께 연결한다.

## 처음 읽을 문서

| 목적 | 문서 |
|---|---|
| 서비스 개요·실행·현재 검증 | [프로젝트 README](../README.md) |
| 사용자와 제품 범위·후속 과제 | [PRD](PRD.md) |
| 다음 Phase와 완료 조건 | [지속형 데모·사용성·새 파일/질문 평가 계획](NEXT_PHASE_DEMO_AND_QUALITY.md) |
| 실제 앱 데모 실행·샘플 재시작 | [지속형 데모 안내](DEMO_RUNBOOK.md), [Phase 1 점검](DEMO_ACCEPTANCE.md) |
| 첫 공개 배포·HTTPS·비용과 상태 | [배포 방향 변경과 검증 상태](PUBLIC_DEPLOYMENT.md) |
| 공개 프론트엔드·Vercel 설정과 검증 | [Vercel 프론트엔드 배포](VERCEL_DEPLOYMENT.md) |
| 최신 main 통합·로그인 디자인 배포 | [커밋·Production·검증 기록](LOGIN_RELEASE.md), [이미지·카피 결정](LOGIN_IMAGE_DECISION.md) |
| 월 고정비 없는 API 구성 검토 | [Vercel API 실제 검증과 필요한 수정](VERCEL_API_FEASIBILITY.md) |
| 서버리스 실행 프로필·원격 연결 준비 | [API 실행 기반 구현과 검증](SERVERLESS_FOUNDATION.md) |
| Supabase 프로젝트·DB·파일 저장소 적용 | [실제 연결·Vercel API 검증과 남은 공개 전환](SUPABASE_SETUP.md) |
| 대용량 파일 보관·원본 다운로드 | [직접 업로드와 검증·만료 처리](DIRECT_UPLOADS.md) |
| 서버리스 문서 색인·지표 갱신·정리 | [Supabase Cron 연결과 실제 검증](SERVERLESS_MAINTENANCE.md) |
| 서버리스 업로드·AI 요청/실행 제한 | [배포 전 제한 구현과 검증](SERVERLESS_RELEASE_GUARDS.md) |
| 공개 서비스·실제 데모 흐름 | [Production 배포와 종합 검증](PUBLIC_DEMO_ACCEPTANCE.md) |
| 첫 분석·실패 복구·직접 체험 과제 | [Phase 2 사용성 개선·검증](DEMO_USABILITY.md) |
| 새 파일·질문의 정확성과 한계 | [Phase 3 본 평가·별도 평가](UNSEEN_DATA_ACCEPTANCE.md) |
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
| 지속형 데모·종료 후 재접속 | [Phase 1: 질문 1개·브라우저 점검 6개](DEMO_ACCEPTANCE.md) |
| 첫 사용·분석 실패 복구 | [Phase 2: 합성 API UI 56개·사용자 관찰 상태](DEMO_USABILITY.md) |
| 새 자료·자연어·저장 상태·범위 경계 | [Phase 3: 최초 28/30 → 전체 30/30, 별도 10/10](UNSEEN_DATA_ACCEPTANCE.md), [공개 보고서](evaluations/unseen-v1/) |
| 파일·누적 장부 전체 흐름 | [6개 질문·29개 점검](WORKSPACE_LIVE_ACCEPTANCE.md), [결과 JSON](../outputs/frontend-design/workspace-live/report.json), [화면 모음](../outputs/frontend-design/integration-validation.html) |
| 최신 파일·저장·샘플 회귀 | [API·브라우저 검증 범위](FILE_SCOPE_AND_FIRST_USE.md#검증) |
| 자연어 50문항 N | [전체 47/50 및 후속 10/10](NATURAL_LANGUAGE_ACCEPTANCE.md), [평가 실행 도구](../scripts/nl-eval/README.md) |
| 합성 PG 데이터 E | [평가 기록](PG_SAMPLE_EVALUATION.md), [CSV·엑셀 사용 순서](../samples/pg-evaluation/README.md) |
| 실제 검색 F | [RAG 평가](RAG_ACCEPTANCE.md) |
| 초기 매출 반영·스케줄러 D | [통합 검증 기록](INTEGRATED_ACCEPTANCE.md) |
| 단계별 원시 근거 | [JSON 보고서·화면](evaluations/) |

fixture 기반 UI 검사, 실제 DB 검사, 실제 LLM 검사는 서로 다른 범위다. 최신 결과를 이전 성적에 합산하지 않으며, 건너뛴 검사는 실행된 것으로 보고하지 않는다. 실제 PG 파일·원격 저장소·운영 부하는 별도 검증이다.

## 디자인 결정과 기록

- [BI·이미지 생성 세션 전달서](brand/BRAND_HANDOFF.md), [새 세션 시작 프롬프트](brand/SESSION_START_PROMPT.md): 제품·확정 디자인·미정 브랜드 항목·참고 화면과 작업 범위.
- [글꼴](TYPOGRAPHY.md): Spoqa Han Sans Neo 확정, 후보·출처·숫자 정렬.
- [컬러 팔레트](COLOR_PALETTE.md), [레퍼런스 비교](PALETTE_REFERENCES.md): Charcoal + Blue, 다크 기본·라이트 지원.
- [프론트엔드 재설계](FRONTEND_REDESIGN.md): 메뉴·접이식 채팅·파일 보관함의 합의와 단계별 진행.
- [HTML 비교·시연 폴더](../outputs/frontend-design/README.md): 초기 정적 시안과 실제 앱 캡처를 구분.
- [초기 엔지니어링 기록](ENGINEERING_HISTORY.md): 관측성·라우터·한국어 검색 개선 당시 수치.
- [초기 에이전트 제안](AGENT_ADVANCEMENT_PLAN.md), [데이터 신뢰성 계획](NEXT_PHASE_DATA_RELIABILITY.md): 과거 계획. 현재 제품 범위는 PRD와 후속 구현 문서를 따른다.
