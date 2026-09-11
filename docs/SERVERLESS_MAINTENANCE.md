# 서버리스 색인·지표 갱신·만료 정리

2026-09-11 · Supabase Cron → `pg_net` → 보호된 Vercel API를 연결하고 실제 정기 실행을 검증했다. 상시 워커나 Redis를 사용하지 않는다.

## 현재 실행 구성

| 작업 | 확인 주기 | 한 번의 처리량 |
|---|---|---|
| 문서·장부 색인 | 1분 | 최대 3개 작업 |
| 저장 지표 갱신 | 1분 | 최대 10개 지표 |
| 만료 업로드 정리 | 10분 | 가져오기 staging 2개 + 보관함 예약 2개 |
| DATAEZ Cron 실행 기록 정리 | 매일 03:17 UTC | 해당 4개 작업의 7일 이전 기록 |

각 Cron은 DB에서 처리할 대상이 있는지 먼저 확인한다. 대상이 없거나 같은 종류의 실행 잠금이 살아 있으면 Vercel을 호출하지 않는다. 지표의 실제 갱신 간격은 기존 `3600`·`86400`초 설정을 따르며, 1분은 실행 시점 확인 주기다. 큐가 쌓이거나 재시도 중이면 그만큼 늦어질 수 있다.

- API 프로젝트: `dataez-api`, `prj_YV4Vf5std97PnGaKwyWzr4LHG940`
- [이 단계에서 검증한 Preview](https://dataez-7hjqd1q8c-gnb1202-navercoms-projects.vercel.app)
- 배포 ID: `dpl_DefPTjXFWaMuwTa5Vo6i9w24E58F`
- 원격 migration: `20260911042155_dataez_maintenance_runs`
- 일반 DB migration: `db/migrations/016_maintenance_runs.sql`
- 공개 프론트엔드는 아직 서비스 준비 화면이다. 이 Preview는 내부 실행용이고 공개 API 전환은 후속 단계다.

## 실행 제한과 복구

`POST /api/internal/maintenance/{index|metrics|cleanup}`는 내부 전용 Bearer secret을 요구한다. 사용자 JWT로 호출하면 401이다. `MAINTENANCE_ENABLED=false`가 기본값이고, 활성화 시 32자 이상의 별도 서버 secret이 필요하다.

`maintenance_runs`는 작업 종류별 실행 잠금·최근 상태·처리 수·시도와 실패 횟수를 저장한다. 원자적 claim으로 중복 실행을 막고, 180초 후에는 중단된 실행의 잠금을 회수할 수 있다. 종료 기록도 같은 lease token일 때만 갱신하여 이전 실행이 새 실행 상태를 덮어쓰지 않는다. 완료 직후 10초 동안 중복 호출을 흡수한다.

작업은 별도 Python 프로세스에서 실행한다. 60초가 지나면 다음 항목을 시작하지 않고, 전체 120초가 지나면 부모가 프로세스를 종료하고 종료를 기다린다. 단순 스레드 timeout과 달리 SDK 재시도·파싱·DB 쓰기가 계속 실행되는 것을 막는다. Vercel의 300초 한도 안에 종료 상태를 기록할 여유를 둔다. 자식은 DB 연결을 최대 1개 사용한다.

이미 커밋된 항목은 유지된다. 종료된 프로세스의 미완료 DB 트랜잭션은 롤백된다. 색인은 기존 600초 lease와 generation fencing, 최대 5회 시도·백오프를 그대로 사용한다. 중단된 지표는 원래 due time으로 다음 실행 대상이 된다. 만료 정리는 원본을 참조하는 `files`가 있으면 삭제하지 않는다.

실행 API의 `succeeded`는 이번 실행 루프가 정상 종료됐다는 뜻이다. 개별 색인 실패·재시도 상태는 `search_index_jobs`, 지표 실패는 기존 `refresh_failures`와 저장 지표 상태에서 확인한다. timeout 때 `processed=0`은 완료 수를 회수하지 못했다는 의미이며, 이전 항목이 전혀 커밋되지 않았다는 보장이 아니다.

## Secret과 권한

- API Preview에 `MAINTENANCE_ENABLED=true`, `MAINTENANCE_SECRET`을 설정했다.
- Supabase Vault에 `dataez_maintenance_url`, `dataez_maintenance_secret`, `dataez_maintenance_bypass`를 저장했다. Cron 명령에는 값 대신 Vault 이름만 들어간다.
- Vercel에는 `DATAEZ Supabase scheduled maintenance`라는 별도 protection bypass를 만들었다. 사용자 계정 토큰이나 Supabase 서버 키를 호출용 헤더로 사용하지 않는다.
- 로컬 재설정에 필요한 값은 ignored `.env.supabase.local`에 있다. `MAINTENANCE_VERCEL_BYPASS`는 로컬 설정용이며 웹에 전달하지 않는다.
- 앱 테이블 27개는 모두 RLS가 켜져 있고 Data API 클라이언트 권한을 차단했다. 새 `maintenance_runs`의 owner는 `dataez_app`이다.
- `anon`과 `dataez_app` 모두 Vault 복호화 뷰를 읽을 수 없는 것을 확인했다. `net`은 Supabase가 관리하는 확장 스키마로 기본 함수 권한을 유지하며, Data API에 노출되지 않는 것을 406 `PGRST106`으로 검증했다. 일반 `postgres`로 관리 소유자의 권한을 회수할 수 있다고 가정하지 않는다.
- Security Advisor는 ERROR/WARN 0개, 서버 전용 테이블의 RLS 정책 없음 INFO 27개다. [진단 설명](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).

## 실제 검증

- 전체 API: **519 passed, 257 skipped**.
- 격리 PostgreSQL: 업로드·보관함·maintenance 검사 **35 passed**. 새 maintenance DB 검사는 동시 claim 4개 중 1개만 성공, lease 만료 회수, 오래된 종료 기록 차단을 확인했다. migration과 앱 초기화의 스키마 일치도 통과했다.
- 배포된 Vercel에서 내부 인증, 세 종류의 자식 프로세스 실행, 실제 문서·장부 임베딩 저장, 지표 `100 → 300`, 다음 갱신 시각 전진, 만료 객체 삭제·유효 객체 보존, 보관함 `document_ready` 상태를 확인했다. [Preview 실행 결과](evaluations/vercel-api/maintenance-vercel.json).
- Supabase Cron의 실제 분 단위 tick으로 색인과 지표 갱신을 재검증했다. 만료 정리는 10분 주기와 동일한 SQL을 `pg_net`으로 즉시 호출했다. [정기 실행 결과](evaluations/vercel-api/maintenance-cron.json).
- 세 `pg_net` 호출은 모두 HTTP 200·timeout 없음으로 완료됐다. 합성 자료 정리 후 4분 이상 실행 횟수가 늘지 않아 대기 작업 없는 API 호출을 생략하는 것도 확인했다. [운영 상태](evaluations/vercel-api/maintenance-operational-state.json), [Preview 배포 상태](evaluations/vercel-api/maintenance-deployment.json).
- 검증에는 작은 합성 문서와 장부의 실제 embedding API를 사용했다. 채팅 agent·자연어 SQL·전체 RAG 답변 품질 검증은 포함하지 않는다.
- 두 실행 모두 합성 계정·가게·객체·장부를 제거했다. 최종 합성 계정·예약·버킷 객체는 0개다. 운영 상태 행과 Cron 작업은 유지한다.

처음 배포에서는 Vercel bootstrap이 추가한 Python 패키지 경로가 자식 프로세스에 전달되지 않아 색인 실행이 실패했다. 부모 `sys.path`를 자식 `PYTHONPATH`로 전달한 뒤 실제 클라우드 실행이 통과했다. 이 최초 실패 1회는 운영 카운터에 그대로 남긴다.

## 운영과 재배포

```powershell
# API migration과 Preview 환경변수를 준비하고 새 배포를 검증한 뒤 실행
python scripts/serverless/configure_maintenance_cron.py --deployment https://dataez-7hjqd1q8c-gnb1202-navercoms-projects.vercel.app

# 위 DATAEZ 작업 4개만 일시정지
python scripts/serverless/configure_maintenance_cron.py --pause

# 실제 원격 검증: 작은 embedding 요청 발생, 합성 데이터 정리 포함
python scripts/serverless/verify_maintenance.py --deployment https://dataez-7hjqd1q8c-gnb1202-navercoms-projects.vercel.app
python scripts/serverless/verify_maintenance.py --deployment https://dataez-7hjqd1q8c-gnb1202-navercoms-projects.vercel.app --scheduled
```

설정 스크립트는 연결된 DATAEZ 프로젝트를 확인하고 내부 상태 조회·인증 거절이 정상인 배포만 등록한다. 같은 이름의 Cron과 Vault 항목을 갱신하므로 중복 작업을 만들지 않는다. Supabase 관리 환경에서 `cron.job`을 직접 UPDATE하는 대신 `cron.alter_job`을 사용한다.

API를 다시 배포한 뒤에는 이 설정 스크립트에 **새 배포 URL**을 넘겨 Vault의 목적지를 갱신해야 한다. 과거 배포를 먼저 삭제하면 정기 호출이 실패한다. 동일 설정으로 재실행하면 일시정지된 DATAEZ 작업을 다시 활성화할 수 있다.

운영 상태는 내부 인증으로 `GET /api/internal/maintenance/status`를 조회하거나 DB의 `maintenance_runs`를 읽는다. Cron 자체 SQL 성공은 HTTP 작업 완료를 뜻하지 않는다. `cron.job_run_details`와 `net._http_response`, 실제 작업 상태를 함께 확인한다. 로그에는 provider 메시지나 원문 대신 작업 종류·오류 종류·종료 코드만 남긴다.

## 후속 공개 배포

[공개 데모 검증](PUBLIC_DEMO_ACCEPTANCE.md) 단계에서 Cron을 `https://dataez-api.vercel.app` 고정 Production 주소로 전환했고 실제 정기 실행을 검증했다.

## 당시 다음 단계

[나머지 업로드 경로와 공유 요청 제한·AI 실행 마감 시간](SERVERLESS_RELEASE_GUARDS.md)을 구현하고 Cron 목적지도 새 Preview로 갱신했다. 최신 주소는 해당 문서를 따른다. 이후 실제 자연어 질문 → SQL → 차트 → 저장 지표 갱신을 검증하고 공개 API/프론트를 연결한다.

공식 근거: [Supabase Cron](https://supabase.com/docs/guides/cron), [Cron·pg_net·Vault 연동](https://supabase.com/docs/guides/functions/schedule-functions), [Vercel 보호 우회용 자동화 토큰](https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/protection-bypass-automation).
