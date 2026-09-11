# Supabase 직접 업로드 — 2026-09-11

파일 보관함은 원본을 브라우저에서 비공개 Supabase Storage로 직접 전송한다. API에는 파일명·크기·SHA-256와 완료 요청만 전달한다. 다운로드도 소유권 확인 후 60초 서명 URL을 발급하여 원본이 API 응답 용량 제한에 걸리지 않게 한다.

## 적용 범위

- 데이터 관리의 파일 보관함과 AI 채팅에서 여는 같은 보관함 컴포넌트에 적용했다.
- CSV·XLSX·XLS·PDF·MD·TXT, 최대 **20 MiB**. 서버 설정이 더 작으면 작은 제한을 적용한다.
- Supabase 이외의 저장소에서는 기존 multipart 업로드·API 다운로드를 유지한다.
- 기존 CSV/Excel 가져오기, 결제 가져오기·매핑, 문서 업로드 패널, 채팅의 **기기 첨부**는 아직 multipart다. 해당 경로의 서버리스 대용량 대응은 후속 작업이다. 보관함에 올린 CSV를 분석 장부로 연결하는 경로는 검증했다.
- 공개 프론트엔드 환경변수는 변경하지 않았다. 보호된 API Preview에만 배포했다.

## 처리 흐름과 권한

1. 로그인된 사용자가 `GET /api/uploads/capabilities`로 전송 방식과 최대 크기를 조회한다.
2. `POST /api/uploads`는 계정·가게 소유권, 확장자·크기·해시를 검사하고 DB에 예약을 기록한다. 요청 ID는 사용자별로 고유하고 다른 파일 정보로 재사용할 수 없다.
3. 서버가 UUID 객체 경로 하나의 업로드 주소를 발급한다. 브라우저는 이 주소에 `PUT`한다. DATA:EZ JWT나 Supabase 서버 키는 Storage 요청 헤더에 포함하지 않는다.
4. `POST /api/uploads/{id}/complete`가 사용자 소유 예약을 잠그고, 실제 원본을 제한된 크기로 읽어 SHA-256와 크기를 대조한다. 원본이 없거나 값이 다르면 파일 목록에 등록하지 않는다.
5. 검증된 객체를 `files`와 `library_entries`에 한 트랜잭션으로 등록한다. 동일 계정·가게·내용은 기존 파일을 재사용한다. 동시 완료 요청도 한 파일로 수렴한다.
6. 원본 다운로드는 `POST /api/library/files/{id}/download-url`에서 소유권을 확인하고 60초 URL을 발급한다. 화면은 브라우저에서 Blob을 받아 원래 한글 파일명으로 다운로드한다.

서명 업로드 URL은 Supabase가 정한 **2시간** 동안 유효하다. `upsert=false`로 발급하므로 업로드한 원본을 이 URL로 바꿀 수 없다. 같은 요청 ID를 재조회할 때 URL을 재발급하지 않아 유효기간이 늘어나지 않는다. URL 발급 응답이 유실되고 실제 전송되지 않은 경우 파일을 다시 선택해 새 요청을 만든다.

예약은 `upload_sessions`에 저장한다. RLS와 `anon`·`authenticated`·`PUBLIC` 권한 차단을 적용했고 `dataez_app` 역할이 소유한다. 모든 사용자 접근은 기존 FastAPI JWT/소유권 검사를 거친다. 업로드 예약과 다운로드 주소 응답은 `private, no-store`다.

## 만료 정리

- 계정당 미완료 예약은 최대 10개다. DB advisory lock과 집계로 함수 인스턴스 사이에도 같은 제한을 적용한다.
- `cleanup_expired_uploads()`는 예약 만료 후 10분이 더 지난 행을 한 번에 최대 2개 잠그고 처리한다. 살아 있는 서명 URL의 객체를 조기 삭제하지 않는다.
- `files`가 참조하는 원본은 유지한다. 미완료·중복 예약의 남은 객체만 삭제한다. DB 실패 시 재실행할 수 있도록 객체 삭제와 예약 삭제 순서를 유지한다.
- 지속 실행 환경의 기존 가져오기 정리 루프에 연결했다. 이후 [서버리스 maintenance Phase](SERVERLESS_MAINTENANCE.md)에서 Supabase Cron의 10분 주기 정리를 연결·검증했다. 정리 전의 만료 예약도 미완료 10개 제한에 포함된다.
- 정리 이후에는 해당 예약 ID의 재시도 대신 보관함에 등록된 파일을 사용한다.

## 마이그레이션

- 일반 DB: `db/migrations/015_direct_upload_sessions.sql`, 앱 초기화 `ensure_upload_sessions()`.
- 원격 Supabase: `20260911040238_dataez_direct_upload_sessions.sql` 적용.
- 로컬 격리 DB에서 전체 migration과 실제 앱 초기화의 컬럼·제약·인덱스 일치를 검증했다.
- 원격 Security Advisor: ERROR/WARN 0개. 서버 전용 테이블 26개의 `RLS Enabled No Policy` INFO는 의도된 접근 방식이다. [진단 설명](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).

## 검증

- API 회귀: **513 passed, 256 skipped**. DB가 필요한 테스트는 이 숫자에 통과로 합산하지 않았다.
- 별도 PostgreSQL 격리 실행: 새 직접 업로드 테스트 13개와 기존 보관함 테스트 15개, **28 passed**. 동시 완료·중복·계정 격리·삭제된 가게·크기/해시 불일치·만료·정리·예약 한도를 검사했다.
- 실제 Supabase: **20 MiB** 직접 PUT, 동일 URL 덮어쓰기 거부, 동시 완료, 20 MiB 다운로드 바이트 일치, 한글 CSV 미리보기·분석 연결·SQL 합계 20,000, RLS 및 CORS 확인. [원격 결과](evaluations/vercel-api/direct-upload-supabase.json).
- 보호된 Vercel Preview에서도 같은 **8개 검증 통과**. [배포 API 결과](evaluations/vercel-api/direct-upload-vercel.json), [배포 상태](evaluations/vercel-api/direct-upload-deployment.json). 배포 ID `dpl_5t76LmZhF7GQH7fpjuqCgrBCBWjf`, 83개 API 파일을 검토한 별도 디렉터리에서 배포했고 비인증 접근은 302 인증 리다이렉트다. 최종 원격 상태는 테이블 26개·RLS 미설정 0개·합성 계정 0개·예약 0개·버킷 객체 0개다.
- 실제 Next.js 화면 + API/Storage fixture: 브라우저의 6 MiB 전송과 작은 JSON 예약, 외부 Storage 요청에 JWT 미포함, 한글 파일명·다운로드 내용 일치, 오류 메시지·용량 초과 차단 4개 통과. [검증 스크립트](../scripts/ui-eval/direct-upload.cjs). 테스트 결과와 화면은 ignored `scripts/ui-eval/artifacts/direct-upload/`에 저장한다.
- TypeScript 검사 통과, ESLint 오류 0개·기존 경고 12개. 추가 실행한 기존 workspace 전체 UI 테스트는 라이트 테마의 고정 배경색 assertion에서 중단됐다(`transparent` vs `white`). 이 전체 시나리오를 통과로 집계하지 않았다. 직접 업로드 화면 검사는 별도로 통과했다.

실행:

```powershell
python scripts/serverless/verify_supabase.py
python scripts/serverless/verify_direct_upload.py
python scripts/serverless/verify_direct_upload.py --deployment https://dataez-moqcvn6gh-gnb1202-navercoms-projects.vercel.app
node scripts/ui-eval/direct-upload.cjs
```

실제 원격 검사는 합성 계정·가게·객체·테이블을 생성하고 종료 시 제거한다. LLM 호출은 하지 않는다. 브라우저 검사는 `http://127.0.0.1:3132/dashboard`의 Next.js 개발 서버와 Playwright가 필요하며, API/Storage 응답을 fixture로 제공한다.

## 다음 완료 조건

[서버리스 색인·정기 갱신과 만료 정리](SERVERLESS_MAINTENANCE.md)는 다음 Phase에서 연결·검증했다. [나머지 업로드 경로·공유 요청 제한·전체 AI 실행 시간 제한](SERVERLESS_RELEASE_GUARDS.md)도 완료했다. 다음은 공개 API·프론트 연결과 실제 질문→SQL→차트→저장 지표 갱신의 공개 환경 검증이다.

공식 계약: [2시간 서명 업로드](https://supabase.com/docs/reference/javascript/file-buckets-createsigneduploadurl), [서명 URL 업로드](https://supabase.com/docs/reference/javascript/file-buckets-uploadtosignedurl), [기간 제한 다운로드](https://supabase.com/docs/reference/javascript/file-buckets-createsignedurl), [Storage REST 명세](https://supabase.github.io/storage/).
