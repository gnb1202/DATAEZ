# Supabase 적용 기록

2026-09-11. DB 스키마·권한·버킷 및 **실제 FastAPI와 원격 DB/Storage 연결 검증 11개 완료**.
이후 공개 프론트와 API를 연결하고 종합 검증했다. [최신 배포 기록](PUBLIC_DEMO_ACCEPTANCE.md).

## 프로젝트

| 항목 | 적용 값 |
|---|---|
| 조직 | `gnb1202's Org` / `fnhmqfnyelrcouzaervv` |
| 프로젝트 | `DATAEZ` / `whbygnzoaehvlddltwlb` |
| 리전 | 서울 `ap-northeast-2` |
| 생성 시 확인 요금 | Free, 월 $0 |
| 상태 | `ACTIVE_HEALTHY` |
| 파일 버킷 | `dataez-files`, 비공개, 파일당 20 MiB |

[프로젝트 대시보드](https://supabase.com/dashboard/project/whbygnzoaehvlddltwlb).
사용자 승인으로 기존 `Briefly`를 일시정지하여 `INACTIVE`를 확인한 뒤 생성했다. `KNUPICK`은 변경하지 않았다.
무료 정책은 [공식 요금 안내](https://supabase.com/pricing)를 기준으로 생성 직전 비용 도구에서 확인했다.

## 적용 내용

- `20260911022219_dataez_initial_schema`: 기존 SQL 15개와 앱 시작 시 추가하던 컬럼을 합쳐 25개 앱 테이블 설치.
  pgvector는 `extensions` 스키마에 설치했다. 첫 마이그레이션 안에서 RLS와 클라이언트 접근 차단까지 적용했다.
- `20260911022227_dataez_access_and_storage`: 서버 전용 `dataez_app` 역할, 기본 권한, 함수 search_path,
  새 테이블 보호용 event trigger, 비공개 Storage 버킷.
- 로컬 파일 버전은 MCP가 반환한 실제 원격 migration version과 맞췄다. 같은 초기 SQL을 중복 실행하지 않는다.
- `supabase/config.toml`은 로컬 CLI 설정이다. 이를 원격 설정 전체에 push하지 않았다.

현재 앱은 자체 JWT와 FastAPI의 사용자·가게 소유권 검증을 사용한다. Supabase Auth로 이전하지 않았다.
따라서 `anon`/`authenticated`용 데이터 접근 정책은 만들지 않았으며 테이블·시퀀스·함수 권한도 회수했다.
`dataez_app`은 앱 테이블 소유자로서 RLS를 우회한다. RLS는 브라우저의 직접 Data API 접근을 차단하고,
사용자 간 격리는 기존 서버 코드가 담당한다. `FORCE RLS`나 일괄 `auth.uid()` 정책으로 바꾸면 현재 앱이 동작하지 않는다.

역할은 `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`이며 서버용 비밀번호와 **LOGIN**을 설정했다.
비밀번호는 Git에서 제외된 `.env.supabase.local`에 저장했다. 기본 `postgres` 자격 증명은 앱에 넣지 않는다.
업로드로 생성되는 public 테이블은 invoker 권한의 event trigger가 즉시 RLS를 켜고 클라이언트 권한을 회수한다.

Storage는 [공식 SQL 버킷 생성 방식](https://supabase.com/docs/guides/storage/buckets/creating-buckets)을 사용했다.
추가 S3 키 발급 없이 공식 Storage REST API를 사용하도록 `STORAGE_BACKEND=supabase`를 추가했다.
기존 local/S3 어댑터도 유지한다. 현재 설정은 다음과 같다.

```dotenv
STORAGE_BACKEND=supabase
SUPABASE_URL=https://whbygnzoaehvlddltwlb.supabase.co
SUPABASE_STORAGE_BUCKET=dataez-files
SUPABASE_SECRET_KEY=<server-only>
S3_PREFIX=uploads
```

`S3_PREFIX`는 기존 공통 객체 경로 변수 이름이다. AWS 리소스를 생성하거나 연결한 것이 아니다.
CLI의 API 키 목록은 현대식 secret 키를 마스킹하여 반환하므로 이를 연결 키로 사용하지 않는다.
현재 연결은 실제로 반환된 legacy service-role JWT로 검증했다. 어댑터는 현대식 `sb_secret_` 키도 지원하지만
해당 방식의 실연결은 아직 검증하지 않았다. 키를 마이그레이션할 때 서버 환경변수만 교체한다.
DB·Storage 서버 키는 문서·Git·브라우저 공개 변수에 저장하지 않는다.

원격 검증 중 확인하여 수정한 사항:

- 한글 파일명을 객체 경로에 사용하면 Supabase가 `InvalidKey`를 반환한다. DB/화면에는 원래 이름을 보존하고 객체 경로는 UUID와 확장자로 만든다.
- CDN에서 교체·삭제 전 내용이 다시 읽히는 것을 확인했다. 분석용 인증 다운로드는 `cacheNonce`로 원본에서 읽는다.
  [공식 캐시 우회 안내](https://supabase.com/docs/guides/storage/cdn/smart-cdn#bypassing-cache).
- TLS 확인은 `conn.pgconn.ssl_in_use`로 수행했다. `pg_stat_ssl`은 pooler→DB 구간이므로 사용자→pooler TLS 증거로 사용하지 않는다.

## 검증 결과

- 격리된 PostgreSQL 16 + pgvector에서 SQL 설치와 실제 앱 초기화 결과의 컬럼·제약·인덱스가 일치했다.
- 서버 역할로 실제 FastAPI 회원가입·로그인·갱신, 두 계정의 가게 접근 격리, 동시 읽기, 새 프로세스 재접속을 검증했다.
- `CREATE TABLE`과 `CREATE TABLE AS`로 생긴 동적 테이블의 RLS 및 클라이언트 권한 차단을 확인했다.
- 원격 Supabase: 25개 테이블 모두 RLS 활성화, 클라이언트 읽기 권한 0개, 비공개 버킷/20 MiB 확인.
- 원격 서버 역할로 합성 계정·가게 생성/읽기와 익명 계정의 읽기 거절을 검증하고 트랜잭션을 롤백했다.
  합성 계정이 남지 않은 것도 확인했다.
- Security Advisor: ERROR/WARN 0개. `RLS Enabled No Policy` INFO 25개는 서버 전용 접근 설계에 따른 결과다.
  [진단 설명](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).
- Performance Advisor: 외래키 인덱스 INFO 20개, 미사용 인덱스 INFO 36개. 새 빈 DB의 미사용 인덱스는 삭제하지 않았다.
  일부 복합 외래키는 기존 단일/선행 인덱스가 있으므로 자동으로 20개를 추가하지 않았다. 실제 부하 확인 후 검토한다.
  [외래키 인덱스 진단](https://supabase.com/docs/guides/database/database-linter?lint=0001_unindexed_foreign_keys),
  [미사용 인덱스 진단](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index).

재실행: `python scripts/serverless/verify_supabase.py` (Docker와 API 의존성 필요).
[로컬 검증 결과](evaluations/vercel-api/supabase-schema-local.json), [원격 적용 확인](evaluations/vercel-api/supabase-remote.json).
로컬 검증용 컨테이너는 제거했다. 이 로컬 결과와 별도로 아래 원격 검증을 수행했다.

### 실제 원격 연결 검증

`python scripts/serverless/verify_supabase_remote.py`는 로컬 FastAPI를 실행하되 DB와 Storage는 실제 DATAEZ 프로젝트를 사용한다.
회원가입·로그인·토큰 갱신, 사용자/가게 격리, 한글 CSV 저장·미리보기·바이트 일치 다운로드,
파일 분석 테이블 생성·SQL 합계 20,000 검증·동적 RLS, staging 교체·삭제, 공개 URL 접근 거절,
동시 읽기, 풀 종료 후 파일 재조회, TLS·prepared statements 미생성까지 **11개 통과**했다.
테스트용 계정·가게·원본 객체·동적 테이블을 제거했다. 실제 LLM 호출은 하지 않았다.
[원격 API 검증 결과](evaluations/vercel-api/supabase-api-remote.json).

연결 기반 단계의 API 회귀 검사는 **511 passed, 243 skipped**였다. 이후 직접 업로드 단계는 **513 passed, 256 skipped**와 별도 DB 검사 **28 passed**다. [직접 업로드 검증](DIRECT_UPLOADS.md).

### Vercel 함수 배포 및 연결 검증

- 프로젝트: `dataez-api` (`prj_YV4Vf5std97PnGaKwyWzr4LHG940`)
- 배포: `dpl_2mB11RCLqPqEm27HUXj8wBDou2Li`, **Preview / READY**
- [보호된 API](https://dataez-6wfjxpyv0-gnb1202-navercoms-projects.vercel.app), Python 3.12, 서울 `icn1`, 2,048 MB, 300초
- 비인증 접근은 Vercel 인증으로 리다이렉트(302)된다. 검증에는 공식 `vercel curl`의 protection bypass를 사용했다.
- 저장소 전체를 업로드하지 않고 검토한 API 소스 81개만 별도 경로에 복사했다. source hash와 dry 파일 목록을 확인했다.
  환경변수 파일은 업로드에서 제외했고 서버 키는 API 프로젝트의 Preview Secret으로 설정했다.
- 배포된 API의 회원가입·로그인·갱신, 소유권 격리, 파일 업로드·미리보기·다운로드·분석 준비·재조회가 통과했다.
  SQL 합계/RLS·staging 조작·TLS 검사는 같은 Supabase를 대상으로 로컬 검증 도구에서 수행했다.
  [검증 11개 결과](evaluations/vercel-api/supabase-vercel-preview.json), [배포 상태](evaluations/vercel-api/supabase-vercel-deployment.json).
- 최초 새 프로젝트 배포는 Vercel이 Production으로 자동 분류하여 Preview 환경변수를 읽지 못했다.
  정상 Preview를 다시 배포·검증하고 해당 최초 배포(`dpl_GBTb2kaYGdCKgzgDLxCHCa7j1Zw7`)는 제거했다.
- 최종 정리 확인: 앱 테이블 25개, RLS 미설정 0개, 합성 계정 0개, 버킷 객체 0개.

클라우드 재검증 명령(로컬 검증용 Vercel 연결 디렉터리 필요):

```powershell
python scripts/serverless/verify_supabase_remote.py --deployment https://dataez-6wfjxpyv0-gnb1202-navercoms-projects.vercel.app
```

## 설정 재사용과 남은 배포

사용자 로그인 후 CLI에서 DATAEZ 조직 접근을 확인했고 `supabase link`를 완료했다.
설치된 CLI의 일부 명령은 `--profile dataez`를 지원하지 않고 설정 파일 경로로 해석한다.
실제로 동작한 공식 기본 프로필 `supabase`를 설정 스크립트에서 사용한다. 추가 로그인은 필요 없다.

```powershell
python scripts/serverless/configure_supabase.py
python scripts/serverless/verify_supabase_remote.py
```

설정 스크립트는 기존 로컬 DB 비밀번호/JWT를 재사용하고 연결 키를 출력하지 않는다.
실제 pooler 호스트는 `supabase link` 결과에서 가져왔으며 transaction 포트 6543, TLS, prepared statements 비활성화로 검증했다.
현재 연결된 호스트는 `aws-0-ap-northeast-2.pooler.supabase.com`이다. Supabase의 호스트 이름이며 별도 AWS 계정을 사용하지 않는다.

보관함의 직접 업로드·완료 검증과 서명 다운로드를 구현했다. 원격 DB에는 `20260911040238_dataez_direct_upload_sessions`를 추가하여 현재 앱 테이블은 26개다. [처리 흐름과 검증](DIRECT_UPLOADS.md).
최신 보호된 API는 [직접 업로드 Preview](https://dataez-moqcvn6gh-gnb1202-navercoms-projects.vercel.app)이며 20 MiB 업로드·다운로드를 포함한 원격 검증 8개가 통과했다. 위의 이전 Preview 11개 기록은 연결 기반 단계의 증거로 유지한다.
이후 [서버리스 색인·정기 갱신·만료 정리](SERVERLESS_MAINTENANCE.md)를 Supabase Cron에 연결하고 실제 정기 실행을 검증했다. 현재 앱 테이블은 27개이며 최신 maintenance 배포 URL은 해당 문서에서 확인한다.
[나머지 업로드 경로와 공유 요청 제한·AI 실행 마감 시간](SERVERLESS_RELEASE_GUARDS.md)까지 보호된 배포에서 검증했다. 현재 앱 테이블은 28개이며, 이후 문서의 Preview가 최신이다.
보호된 API Preview 배포와 실제 함수 연결은 검증했다. 위 공개 전환 요건이 충족되면 웹의 `API_URL`을 연결한다.

위 내용은 연결 기반 단계의 기록이다. 이후 [공개 데모 단계](PUBLIC_DEMO_ACCEPTANCE.md)에서 웹의 API 주소를 Production에 연결했다. 별도 AWS 리소스는 생성하지 않았다.
