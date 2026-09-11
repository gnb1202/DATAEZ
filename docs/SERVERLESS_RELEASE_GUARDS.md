# 서버리스 업로드 경로와 AI 실행 제한

2026-09-11 보호된 배포 단계 검증 완료. 이후 [공개 데모 배포와 검증](PUBLIC_DEMO_ACCEPTANCE.md)까지 완료했다. 아래는 이 단계 당시 기록이다.

- API Preview: https://dataez-geujmxikb-gnb1202-navercoms-projects.vercel.app
- API 배포: `dpl_5B7QQ91rgqhe4nLxJRazu9iA4Lqs`, Python 3.12, 서울, 300초 함수
- 웹 Preview: https://dataez-ij1lu5xpn-gnb1202-navercoms-projects.vercel.app
- 웹 Preview는 API 환경변수를 설정하지 않은 상태의 빌드 검증이며 공개 사이트를 변경하지 않았다.
- Supabase: `whbygnzoaehvlddltwlb`, 앱 테이블 28개, 전부 RLS 활성화
- 마이그레이션: `20260911045751_dataez_request_limits`

## 원본 전송

보관함 외에 다음 화면도 브라우저 → Supabase signed PUT → 완료 검증 → API에 파일 ID 전달 방식으로 전환했다.

| 경로 | API 필드 | 동작 |
| --- | --- | --- |
| CSV/Excel 장부 가져오기 | `stored_file_id` | 같은 원본의 장부 재사용, 원본 중복 저장 방지 |
| 장부 행 추가 API | `stored_file_id` | 기존 append 의미 유지: 요청마다 행 추가 |
| 참고 문서 등록 | `stored_file_id` | 원본과 색인 작업 재사용 |
| 결제 파일 컬럼 확인·검사·가져오기 | `stored_file_id` | 원본 재전송 없이 기존 검토/배치 절차 사용 |
| 채팅의 새 파일 첨부 | `stored_file_ids` JSON 배열 | 기존 첨부 파일 도구에 원본 제공; 장부 생성 시 보관 원본 재사용 |

`upload_sources.py`에서 소유 계정, 현재 가게, 제거 여부, 확장자, 크기와 SHA-256을 확인한다. 다른 가게의 원본을 이 경로로 가져올 수 없다. 여러 가게 분석은 기존 보관함의 명시적 분석 범위 선택을 사용한다. 파일과 ID를 동시에 보내면 422다.

질문은 1~8,000자, 모델의 개별 응답은 최대 4,096 토큰으로 제한한다. 파일당 최대 20 MiB. 채팅은 최대 3개, 합계 20 MiB. 기존 multipart의 읽기도 최대 크기+1 바이트로 제한한다. 로컬/S3 환경은 기존 multipart와 호환된다. 파일을 소비하는 배포 API 요청에는 원본 바이트가 들어가지 않는다.

컬럼 검사 전에 원본이 보관함에 저장됨을 화면에 명시했다. 검사 자체는 장부 행을 변경하지 않는다. 결제 가져오기는 검토용 staging과 감사 이력을 위한 기존 원본 보존 절차를 유지한다. 브라우저가 중간에 취소하면 예약된 업로드는 기존 만료 정리가 처리한다.

## 요청 제한

서버리스 프로필에서 `request_limits`의 원자적 UPSERT로 인스턴스 간 제한을 공유한다. 계정/IP 원문 대신 키의 SHA-256만 저장한다. 활성 창의 요청 수는 거절 시 증가하거나 만료 시간이 연장되지 않는다. 만료된 행은 요청당 최대 100개 정리한다. DB 확인 실패 시 503으로 차단하며 메모리 제한으로 자동 우회하지 않는다.

| 설정 | 서버리스 기본값 |
| --- | --- |
| `AI_USER_REQUESTS_PER_DAY` | 계정당 30회 |
| `AI_TOTAL_REQUESTS_PER_DAY` | 앱 전체 100회 |
| `AGENT_TIMEOUT_SECONDS` | 200초, 설정 범위 10~240초 |
| `AGENT_MAX_ITERATIONS` | 8회 |
| `AGENT_MAX_TOKEN_BUDGET` | 24,000 토큰 |

일일 제한은 첫 허용 요청부터 24시간인 고정 창이며 자정 초기화가 아니다. 오류·연결 종료도 시도 횟수에 포함하며 환불하지 않는다. 계정 한도 통과 뒤 전체 한도로 거절된 요청도 계정 횟수를 소비하므로 보수적으로 제한된다. 사용자별 분당 분석 제한은 IP 변경으로 우회되지 않는다.

요청 수와 실행 시간에 대한 제한이며 **금액 기준 과금 상한은 아니다**. 토큰 예산은 기존 반복 간 검사이므로 마지막 한 번의 응답이 임계치를 넘을 수 있다. 배경 임베딩은 채팅 요청 한도에 포함되지 않는다. 지속 실행 개발 환경에서는 기존 메모리 제한을 유지한다.

## 실행 종료와 복구

서버리스의 동기·스트리밍 AI는 별도 Python 프로세스에서 실행한다. 부모가 전체 200초 마감과 스트림 종료를 처리하고 자식 프로세스를 종료한 뒤 회수한다. 단순히 `asyncio.to_thread`의 대기만 취소하는 방식이 아니다. 자식의 툴 스레드도 함께 종료된다. 자식에게 설정과 Python 모듈 경로를 전달하되 자격증명이나 원본은 로그에 출력하지 않는다.

이미 커밋된 변경은 유지된다. 미완료 트랜잭션은 연결 종료에 따라 롤백된다. 시간 초과 안내에는 일부 변경이 반영되었을 수 있음을 명시한다. 스트리밍 오류를 받으면 지금까지 받은 도구 단계와 중단 메시지를 분석 이력에 저장한 후 오류 프레임을 보낸다. 클라이언트가 먼저 연결을 닫은 경우 응답 저장은 보장하지 않으므로 장부와 감사 이력을 확인해야 한다. 중단된 호출은 공급자 최종 usage를 받지 못할 수 있어 사용량이 일부 누락될 수 있지만 시도 횟수는 유지된다.

## 검증

- API 전체: **525 passed, 260 skipped**. DB 환경이 필요한 테스트는 별도 실행.
- 임시 PostgreSQL: **44 passed**, 보관함·직접 업로드·maintenance 및 새 요청 제한/원본 경로 포함.
- 실제 OS 프로세스: 시간 초과 및 스트림 종료 후 자식이 회수되는지 검증.
- 보호된 API: **6개 검사** 통과. 장부 재사용/append, 범위 차단, 컬럼 검사/결제 배치, 문서 등록, 실제 LLM 스트리밍/usage, 공유 한도/RLS.
- 실제 AI 호출: 최종 배포에서 인사 1회, 6,175 토큰. 직전 배포 검증의 인사 1회를 합쳐 이번 단계에서 실제 호출은 총 2회. 추정 비용은 telemetry 모델 단가 기준이며 청구액이 아니다.
- 실제 브라우저: **2개 검사** 통과. 채팅 6 MiB와 문서 6 MiB가 Storage PUT으로 전송되고 API에는 ID만 전달됨. API/Storage 응답은 fixture 사용.
- TypeScript 성공. 변경 프론트 파일 ESLint 오류 0, 기존 `ledger-import-panel.tsx` effect 의존성 경고 1개.
- Vercel 웹 빌드 Next.js 16.3.4 성공. 로컬 브라우저 확인은 설치된 Next.js 16.1.6 사용.
- 원격 테스트 계정·원본·예약 정리 완료. 전체 AI 사용 횟수 2는 실제 사용 기록으로 유지.
- Supabase Cron 4개 ACTIVE, Vault API URL은 최신 Preview로 갱신.

기존 광범위 UI 테스트의 라이트 모드 tooltip 배경 이슈는 이 검증과 별개로 남아 있다([직접 업로드 검증](DIRECT_UPLOADS.md)). 추가 실행한 `import-validation.cjs`와 `ledger-imports.cjs`도 현재 앱의 `/api/library/files/sample-workspace` mock 누락으로 시작 단계에서 실패했다. 해당 기존 스크립트는 업로드 capabilities fixture도 갱신해야 한다. 전체 UI 테스트가 통과했다고 간주하지 않는다.

재검증:

```powershell
python -m pytest api/tests -q
python scripts/serverless/test_release_guards.py
python scripts/serverless/verify_release_guards.py --deployment https://dataez-geujmxikb-gnb1202-navercoms-projects.vercel.app
node scripts/ui-eval/upload-sources.cjs
```

브라우저 검증은 `http://127.0.0.1:3132/dashboard`의 로컬 웹 서버와 Playwright/Edge가 필요하다. 원격 검증은 `.env.supabase.local` 자격증명과 실제 AI 호출을 사용한다. 보고서는 `docs/evaluations/vercel-api/release-guards-*.json`에 저장한다.

## 다음 배포 단계

1. 기존 UI 회귀 fixture와 알려진 라이트 tooltip 검사를 보완한 뒤 API Production 주소와 접근 정책을 확정하고 프론트 `NEXT_PUBLIC_API_URL`·CORS 연결.
2. 공개 주소에서 로그인 → 직접 업로드 → 자연어 분석 → 대시보드 저장/새로고침을 종합 확인.
3. 포트폴리오용 데모 계정/데이터 정리와 배포 문서 갱신, 변경사항 커밋·원격 반영.

이번 단계에서는 Git 커밋·push 또는 공개 프론트의 API 연결을 실행하지 않았다.
