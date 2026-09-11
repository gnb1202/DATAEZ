# Vercel API 실행 기반과 Supabase 연결 준비

2026-09-11 · API 실행 기반·원격 Supabase DB/Storage 연결 검증 완료. [최신 연결 기록](SUPABASE_SETUP.md).

이 단계는 [적합성 검증](VERCEL_API_FEASIBILITY.md)의 첫 구현 단계다.
원격에서 파일 업로드·AI·색인·예약 갱신까지 동작하는 공개 서비스가 완성된 상태는 아니다.
기존 Vercel 프론트는 서비스 준비 화면을 유지한다.

## 구현

- `api/index.py`가 Vercel 실행 프로필을 선택한다. Docker는 기존 `app.main:app`을 사용한다.
- Python 3.12와 서울 함수 리전, 최대 300초 실행을 `api/.python-version`, `api/vercel.json`에 명시했다.
- 서버리스에서는 요청 시작 시 마이그레이션·데이터 정리를 실행하지 않는다.
  지표·색인·정리의 상시 루프도 시작하지 않으며, 잘못 켠 설정은 시작 단계에서 거부한다.
- DB 풀은 기본 최소 0 / 최대 2, 대기 5초, 유휴 60초이며, 연결 생성은 잠금으로 보호한다.
  연결을 꺼낼 때 연결 상태를 확인하고, transaction pooler용으로 prepared statements를 비활성화한다.
  종료 시 풀 대기는 0.25초로 제한한다.
- 로컬 디스크를 영구 저장소로 사용하는 서버리스 설정은 거부한다. Supabase 공식 Storage API와 기존 S3 호환 저장소를 지원한다.
- `python -m app.migrate`로 스키마 초기화·갱신을 배포와 분리했다. 새 DB에는 `--bootstrap-sql ../db/init.sql`을 지정한다.
  마이그레이션은 단일 실행자가 수행해야 하며, 함수 빌드·콜드 스타트에 연결하지 않는다.
- 설정 오류 출력에는 입력값을 숨겨 DB 연결 문자열·키가 예외 출력에 노출되지 않도록 했다.

## 설정과 원격 연결 절차

API 전용 프로젝트의 Root Directory는 `api`다. 기존 웹 프로젝트의 Root Directory `web`를 변경하지 않는다.
필요한 변수 이름은 [환경변수 예시](../api/.env.vercel.example)에 있다. 실제 키는 Vercel API 환경변수나
Git에서 제외된 로컬 파일에만 저장한다. `NEXT_PUBLIC_` 변수로 전달하지 않는다.

1. DATA:EZ 전용 Supabase 프로젝트는 `gnb1202's Org`의 `whbygnzoaehvlddltwlb`로 생성했다.
   사용자 승인으로 `Briefly`를 일시정지했고 `KNUPICK`은 변경하지 않았다.
   [Supabase 적용 기록](SUPABASE_SETUP.md)에 스키마·권한·Storage와 원격 연결 검증을 기록했다.
2. 해당 프로젝트에서 앱 테이블의 Data API 노출을 차단하고, 노출 스키마의 테이블에는 RLS를 설정한다.
   현재 자체 JWT 인증과 사용자 ID 검증을 유지한다. 기존 서비스 DB에 기본 스키마를 섞어 설치하지 않는다.
3. Supabase Connect 화면의 **Transaction pooler** URI를 API `DATABASE_URL`로 사용한다.
   실제 URI를 복사하고 TLS(`sslmode=require`)를 사용한다. 호스트 이름을 리전만으로 추측하지 않는다.
4. Supabase에서는 `supabase/migrations`의 버전 관리된 SQL을 사용한다. 이미 초기 스키마와 권한이 적용된
   DATAEZ 프로젝트에 아래 초기화 명령을 다시 실행하지 않는다. 다음 명령은 기존 Docker 등 별도 환경의 초기화용이다:

   ```text
   python -m app.migrate --bootstrap-sql ../db/init.sql
   ```

   기존 DB 갱신에는 `--bootstrap-sql`을 생략한다. 초기화 명령은 기존 초기화 코드의 데이터 정리도 수행하므로
   임의의 다른 프로젝트나 운영 DB에 실행하지 않는다. RLS·권한 설정과 원격 advisor 확인은 프로젝트 지정 후 함께 수행한다.
5. 비공개 Storage 버킷과 Supabase 서버 API 키를 설정한다. S3 호환 방식은 별도의 선택지다.
6. `/ready`에서 DB 접근을 확인하고 원격 회원가입·로그인·계정 격리를 검증한다. `/ready`의 `SELECT 1` 성공은
   스키마·Storage·백그라운드 작업까지 준비됐다는 의미가 아니다.

공식 연결 근거: [Supabase DB 연결](https://supabase.com/docs/guides/database/connecting-to-postgres),
[psycopg prepared statements 비활성화](https://supabase.com/docs/guides/troubleshooting/disabling-prepared-statements-qL8lEL).

## 검증

- API 테스트: **499 passed, 243 skipped**. 별도 DB·실제 모델 등이 필요한 검사는 통과로 합산하지 않았다.
- 격리된 임시 PostgreSQL + pgvector에서 실제 스키마 초기화를 두 번 실행했다.
- 실제 FastAPI·DB로 두 계정 로그인·토큰 갱신, 가게 소유권 격리, 최대 2개 연결 풀에서 동시 읽기 12회,
  자동 prepared statements 미생성을 확인했다.
- 새로운 Python 프로세스에서도 다시 로그인하고 저장된 가게를 읽었다. 각 프로세스 5개 검사가 통과했다.
- 검증 DB 컨테이너는 작업 소유권을 확인한 뒤 삭제했다. Supabase 원격 pooler·Storage 검증을 대신하지 않는다.

실행: `python scripts/serverless/verify.py` (Docker와 API 의존성이 설치된 Python 필요).
[실제 DB 검사 결과](evaluations/vercel-api/serverless-foundation.json).

## 다음 단계

원격 스키마·권한·비공개 버킷과 pooler·Storage 연결, [보관함 직접 업로드](DIRECT_UPLOADS.md),
[제한된 색인·정기 갱신·만료 정리 호출](SERVERLESS_MAINTENANCE.md)을 연결·검증했다.
[나머지 업로드 경로, 공유 요청 제한과 전체 AI 실행 마감 시간](SERVERLESS_RELEASE_GUARDS.md)도 구현·원격 검증했다. 다음은 공개 API와 프론트 연결이다.
공개 전환은 실제 자연어 분석과 저장 지표 갱신까지 통합 검증한 뒤 진행한다.
