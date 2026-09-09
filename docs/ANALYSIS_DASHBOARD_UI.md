# 분석 결과·대시보드 UI

> 2026-09-10 후속 구현: [파일 원본·누적 장부 범위, 저장 전 설정, 샘플 첫 사용 안내](FILE_SCOPE_AND_FIRST_USE.md). 아래의 이전 단계 기록보다 이 문서의 최신 동작을 우선합니다.

2026-09-10 · 프론트엔드 Phase 4 완료. [실제 앱 화면 비교](../outputs/frontend-design/app-workspace.html?phase=analysis-dashboard).

## 구현 결과

- 실제 Next.js 앱의 분석 결과, 대시보드 위젯, 지표 미리보기를 **Apache ECharts 6.1.0 / SVG**로 전환했다. 필요한 차트·컴포넌트를 동적으로 불러온다. 기존 Recharts 공용 UI 파일과 의존성은 호환용으로 남아 있다.
- 확정한 **Charcoal + Blue / Spoqa Han Sans Neo**를 차트와 툴팁에도 적용했다. 다크·라이트·시스템 테마, 동작 줄이기 설정, 컨테이너 크기 변경을 지원한다.
- 분석 결과의 그래프·기간·출처·계산 설명을 앞에 배치하고, AI 설명·선택 파일·연결 장부 범위를 뒤에 배치했다. 집계표·SQL 버튼에서 정확한 값, 수식 입력값, 절댓값 처리, 출처별 연결·필터, 실행 SQL과 매개변수를 확인한다. 기록되지 않은 기간이나 SQL을 추정해서 표시하지 않는다.
- 금액 문자열은 집계표와 툴팁에서 정밀도를 보존한다. 그래프 위치만 숫자로 변환한다. NULL은 0으로 바꾸지 않으며, 합계 0인 도넛은 안내를 표시하고 음수가 있는 도넛 요청은 막대그래프로 표시한다. 툴팁 라벨은 HTML로 해석하지 않는다.
- 방향키/Home/End/Escape로 차트의 정확한 값을 탐색한다. 집계 항목이 24개를 넘으면 범위 조절기를 표시한다. 상세 집계표는 25개씩 페이지를 이동한다.
- 저장 상태 확인 → 미저장 → 저장 중 → 저장 완료 또는 오류/재시도를 표시한다. 저장 완료 후 해당 위젯으로 이동하고 포커스를 준다. 다시 접속해 분석 이력을 열어도 저장 상태를 확인한다. AI 도구가 이미 저장한 지표는 도구 결과의 정의와 ID로 식별한다.
- KPI 숫자를 강조하고, 지표 생성 폼·시작 안내를 접을 수 있게 묶었다. 출처·기간과 오류는 바로 표시하고, 계산 상태는 펼쳐서 확인한다. 갱신 주기·재계산·수정 이력·삭제는 기존 기능을 유지한다.
- 로딩 뒤 마운트된 그리드가 추정 너비 1280px를 유지하던 문제를 수정했다. 실제 DOM 노드를 관찰하고, 넓은 화면은 12열로 배치한다. 채팅 열기·화면 너비 변경은 배치를 서버에 쓰지 않으며, 사용자가 드래그·크기 조절을 마쳤을 때만 저장한다.

## 저장 계약

`CreateMetricRequest`와 `CreateWidgetRequest`에 선택적인 `save_key`를 추가했다. 결과의 메시지 ID와 차트 순서로 키를 만들고, 사용자·가게·키를 기준으로 동일 저장 요청을 구분한다.

같은 키의 동시 요청은 PostgreSQL 트랜잭션 잠금으로 직렬화하고, 기존 위젯을 반환한다. 내용이 다른 요청은 HTTP 409로 거절한다. 스냅샷 배치 좌표는 내용 해시에 포함하지 않아 응답 재시도 중 레이아웃이 달라져도 중복 생성하지 않는다. 갱신·수정으로 교체되는 `widget_data` 밖에 저장 키를 둔다. 저장 응답을 잃으면 UI가 위젯 목록을 먼저 조회한 뒤 같은 키로 재시도한다.

마이그레이션은 `db/migrations/011_widget_save_keys.sql`이며 API 시작 시 `ensure_widget_saves()`로도 적용한다. 기존 클라이언트의 키 없는 저장은 기존 동작을 유지한다. 기존 데이터의 중복을 제거하거나 서로 다른 질문의 결과를 임의로 합치지는 않는다. 위젯을 명시적으로 삭제하면 같은 분석 결과를 다시 저장할 수 있다.

## 검증

| 검증 | 결과 |
|---|---|
| Next.js production build / TypeScript | 통과 |
| 변경 프론트 파일 ESLint | 오류·경고 0 |
| 백엔드 관련 테스트 | 215개 통과: 기본 지표·API·도구·통합 지표 148개, 다중 가게·그룹 수식·수정 이력 67개 |
| 실제 PostgreSQL 저장 테스트 | 동시 요청 5건, 재계산 후 재시도, 내용 충돌, 가게·사용자 분리, 삭제 후 재저장, 정밀 소수 확인 |
| `analysis-dashboard.cjs` | 11개 검증 그룹 통과 |
| `workspace.cjs` | 14개 회귀 검증 그룹 통과 |
| `file-library.cjs` | 6개 회귀 검증 그룹 통과 |

브라우저는 Windows Edge headless와 실제 Next.js 빌드를 사용했다. **브라우저 API는 테스트 응답**이며 실제 PostgreSQL 트랜잭션 검증은 별도다. 이 Phase 4 UI 시험에서는 실제 LLM과의 전체 흐름을 재실행하지 않았다. 이후 [실제 API·LLM 통합 검증](WORKSPACE_LIVE_ACCEPTANCE.md)을 완료했다. [브라우저 결과 JSON](../outputs/frontend-design/workspace-app/analysis-dashboard-report.json).

재실행 시 테스트 전용 DB 주소를 `DATAEZ_TEST_DATABASE_URL`과 `DATAEZ_RAG_TEST_DATABASE_URL`에 설정한다. 다음 테스트들은 고유 스키마에서 실행하고 자기 스키마만 정리한다.

```powershell
python -m pytest api/tests/test_widget_saves.py api/tests/test_dashboard_metrics.py api/tests/test_dashboard_metrics_postgres.py api/tests/test_integration.py api/tests/test_agent_tools.py api/tests/test_store_metrics.py api/tests/test_grouped_formula_metrics.py api/tests/test_formula_revisions.py api/tests/test_multi_metrics.py api/tests/test_multi_metrics_sql.py -q
npm.cmd --prefix web run build
# 실제 Next.js 앱을 3132 포트에서 실행한 뒤:
node scripts/ui-eval/analysis-dashboard.cjs
node scripts/ui-eval/workspace.cjs
node scripts/ui-eval/file-library.cjs
```

## 다음 범위

보관함 파일 선택의 현재 계산 범위는 **연결 장부 전체 + 지표의 기간·필터**다. 원본 파일의 행만 분석하는 기능은 별도 설계가 필요하다. 그다음 실제 API·DB·LLM으로 파일 선택 → 질문 → 저장 → 갱신 흐름을 통합 검증하고 첫 사용 안내를 다듬을 수 있다. 원격 Supabase 연결과 실제 PG 연동은 이번 단계에 포함하지 않았다.

## 참고한 공식 자료

- [ECharts 모듈 구성](https://echarts.apache.org/handbook/en/basics/import/)
- [차트 크기와 수명 관리](https://echarts.apache.org/handbook/en/concepts/chart-size/)
- [ARIA 지원](https://echarts.apache.org/handbook/en/best-practices/aria/)
- [ECharts 6.1.0 릴리스](https://github.com/apache/echarts/releases/tag/6.1.0)
