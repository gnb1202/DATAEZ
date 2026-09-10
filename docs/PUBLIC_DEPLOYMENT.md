# DATA:EZ 첫 공개 데모 배포안

2026-09-11 · 배포 후보 `codex/public-demo-deployment`의 누적 작업을 main에 통합했다.

**현재 상태: [프론트엔드](https://dataez.vercel.app)를 Vercel에 공개 배포했다. AWS API와 Supabase DB·Storage 연결은 아직 진행 전이다.** 현재 공개 화면은 서비스 준비 안내를 표시하고 로그인·회원가입을 비활성화한다. [Vercel 설정과 공개 검증 결과](VERCEL_DEPLOYMENT.md)를 참고한다. Phase 3와 브랜드를 포함한 누적 작업은 main에 통합했으며 기존 미커밋 상태는 로컬 백업으로 보존했다. 사람의 사용성 관찰보다 공개 데모 준비를 먼저 진행한다. AWS 서버는 아직 생성하지 않았다.

## 2026-09-11 배포 방향 결정

- 웹은 Vercel, FastAPI와 색인·지표 갱신 작업은 AWS에서 실행하는 방향이다. AWS 인스턴스 크기와 비용은 DB 분리 후 필요한 메모리를 확인해 확정한다.
- PostgreSQL과 pgvector, 원본 CSV·Excel은 우선 Supabase Free를 사용한다. 기존 자체 JWT 인증을 유지할 수 있으며, Supabase Auth 전환은 이번 결정에 포함하지 않는다.
- Free 한도는 DB 500MB, 원본 Storage 1GB, 단일 파일 50MB다. DB 테이블·벡터·인덱스는 DB 용량을, 원본 파일은 Storage 용량을 사용한다. 파일을 S3로 옮겨도 DB 500MB 한도는 별도로 남는다.
- 무료 프로젝트는 7일간 DB 활동이 적으면 일시 중지될 수 있고 자동 백업이 포함되지 않는다. 이를 수용하고 실험·데모부터 시작한다. 2026-09-11의 로컬 데모 DB 측정값은 10,697,751바이트이며, Supabase 이전 후 사용량이나 원격 부하 검증 결과가 아니다.
- 현재 `deploy/compose.public.yaml`은 여전히 웹·DB·파일을 한 VM에 두는 아래의 이전 구성이다. Supabase 배포용으로 그대로 실행하지 않는다. API 전용 배포 설정, Supabase 연결·스키마·접근 권한, 비공개 버킷, Vercel 환경변수와 CORS를 준비한 뒤 실제 파일 왕복·계정 격리·분석·저장·갱신을 검증해야 한다.

근거: [Supabase 요금과 Free 한도](https://supabase.com/pricing), [프로젝트 일시 중지](https://supabase.com/docs/guides/platform/free-project-pausing), [DB 용량 산정](https://supabase.com/docs/guides/platform/database-size).

### 향후 원본 저장소를 AWS S3로 전환

`api/app/storage.py`는 boto3 S3 클라이언트와 사용자 지정 endpoint를 지원하고 DB에는 원본의 `storage_key`를 저장한다. Supabase Storage도 S3 프로토콜을 지원하므로 같은 저장소 인터페이스를 재사용할 수 있다. 기존 S3 호환 어댑터 테스트는 모의 클라이언트 검사이며 실제 Supabase 또는 AWS S3 이전 완료를 뜻하지 않는다.

현재 설정은 배포 전체에서 저장소 하나를 선택한다. 전환 시 원본과 필요한 임시 업로드 객체를 같은 키로 대상 버킷에 복사하고 파일 수·크기·바이트 해시를 검증한다. 복사 중 추가 업로드나 작업이 생기지 않도록 쓰기를 잠시 멈추거나 최종 증분 복사를 수행해야 한다. 이후 버킷·리전·서버 자격 증명을 변경하고, AWS S3를 사용할 때 Supabase용 endpoint와 자격 증명이 남지 않게 한다. 다운로드·재분석·계정 격리를 확인한 뒤 기존 저장소 정리를 별도로 진행한다. 환경변수 변경만으로 파일이 자동 이전되지는 않는다.

동일한 객체 키와 파일 ID를 보존하면 기존 파일 참조를 유지할 수 있다. DB와 대시보드는 Supabase에 남겨 둘 수 있다. 두 저장소에 파일을 나누어 보관하며 동시에 읽는 기능은 현재 구현되지 않았으며, 필요해질 때 파일별 저장소 정보를 추가한다.

근거: [Supabase S3 호환 범위](https://supabase.com/docs/guides/storage/s3/compatibility).

## 이전 단일 서버 후보와 비용

현재 웹·API·PostgreSQL 구조를 유지하는 **AWS Lightsail 단일 서버**를 첫 후보로 삼는다. 서울 `ap-northeast-2`, Ubuntu 24.04 LTS(`ubuntu_24_04`), IPv4 포함 2GB/2 vCPU/60GB(`small_3_0`)의 표시 요금은 **월 최대 $12**다. 실제 AWS 읽기 전용 API로 해당 리전의 활성 번들과 블루프린트를 확인했다. 현재 연결 계정에서 서울 Lightsail 인스턴스와 Route 53 hosted zone은 조회되지 않았다. 다른 리전·외부 DNS까지 비어 있다는 의미는 아니다.

모델 API 사용료, 도메인 등록, 별도 스냅샷·전송 초과·세금은 위 서버 요금과 별도다. 무료 체험 자격을 확인하지 않았으므로 무료로 가정하지 않는다. 2GB는 소규모 합성 데모의 시작 후보이며 VM에서의 실제 메모리·부하는 생성 후 확인한다. 빌드 중 메모리가 부족하면 다른 환경에서 이미지를 빌드해 전달할 수 있다.

Google Cloud에서도 VM 한 대로 같은 구성을 운영할 수 있다. Cloud Run은 트래픽이 없을 때 인스턴스를 0으로 줄일 수 있지만, 현재 API 안에서 동작하는 색인 작업·지표 주기 갱신에는 최소 인스턴스 유지 또는 작업 구조 변경이 필요하다. 이번에는 이미 검증한 Compose 경로를 활용한다.

근거: [AWS 번들 요금](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html), [Lightsail 요금·추가 항목](https://aws.amazon.com/lightsail/pricing/), [Cloud Run 확장과 백그라운드 작업](https://docs.cloud.google.com/run/docs/about-instance-autoscaling).

## 이전 단일 서버 배포 파일

- [공개용 Compose 추가 설정](../deploy/compose.public.yaml): 기존 `docker-compose.yml`에 덧붙여 API·웹의 직접 공개 포트를 제거하고 HTTPS 프록시를 추가한다.
- [Caddy 설정](../deploy/Caddyfile): `/api/*`, `/health`, `/ready`를 API에 전달하고 나머지는 웹에 전달한다. SSE 응답을 버퍼링하지 않으며 `/metrics`는 공개하지 않는다.
- [환경변수 예시](../deploy/.env.public.example), [설정 검사](../deploy/check.py), [격리 검증 도구](../deploy/verify.py).

프록시만 80·443을 공개한다. PostgreSQL·원본 파일·인증서 상태를 각각 영구 볼륨에 보관한다. API는 기존처럼 프로세스·복제본 1개이며, `APP_ENV=production`과 공개 주소에 맞는 CORS를 사용한다. Caddy가 전달하는 실제 클라이언트 IP를 신뢰하도록 설정하므로 로그인 요청 제한이 프록시 한 주소로 합쳐지지 않는다. API 포트는 직접 외부에 노출하지 않는다.

브라우저 API 주소와 공유 이미지 주소는 같은 `PUBLIC_ORIGIN`으로 빌드한다. 주소가 바뀌면 웹 이미지를 다시 빌드해야 한다. 웹 Docker 런타임은 지원 종료된 Node 20에서 Node 24 LTS로 변경했다. [Node 지원 현황](https://nodejs.org/en/about/previous-releases).

이미지 빌드 중 기존 의존성 경고를 확인해 Next.js와 `eslint-config-next`를 **16.3.4**로 올리고, 호환 범위의 간접 의존성을 잠금 파일에 갱신했다. 기존 16.1.6은 [Next.js의 AVIF 처리 보안 공지](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4)의 영향 범위였다. 수정 후 `npm audit --omit=dev`와 전체 `npm audit` 모두 알려진 취약점 **0건**이다. 이는 해당 시점의 npm 의존성 검사이며 OS·Python을 포함한 전체 시스템 보안 보증은 아니다.

## 이전 단일 서버 구성의 실행 절차

아래 절차는 서버 생성 비용과 사용할 주소를 확정한 뒤 실행한다. 새 서버와 전용 데이터 볼륨을 사용하며 로컬 데모 계정·파일을 복사하지 않는다.

1. Ubuntu 서버에 [Docker Engine과 Compose 플러그인](https://docs.docker.com/engine/install/ubuntu/)을 설치한다. Compose **2.24.4 이상**이 필요하다. `!reset`을 지원하지 않으면 설정 검사가 실패한다.
2. 서버의 고정 IPv4를 확보하고 도메인 A 레코드를 연결한다. Lightsail 방화벽은 HTTP/HTTPS 80·443, SSH 22는 관리자의 허용 IP로 제한한다. 도메인 소유·사용 권한은 실제 주소를 정할 때 확인한다.
3. 이 배포 브랜치의 코드를 서버에 체크아웃하고 아래 설정을 작성한다. 키는 채팅이나 Git에 올리지 않고 서버 파일에 입력한다.

```bash
cp deploy/.env.public.example .env.public
chmod 600 .env.public
# PUBLIC_HOST, PUBLIC_ORIGIN, POSTGRES_PASSWORD, JWT_SECRET_KEY, OPENAI_API_KEY 입력
python3 deploy/check.py --env-file .env.public
docker compose --env-file .env.public -p dataez-public \
  -f docker-compose.yml -f deploy/compose.public.yaml up --build -d --wait
```

`PUBLIC_HOST`는 실제 DNS 이름이며 `PUBLIC_ORIGIN`은 경로 없는 `https://그이름`이다. DB 비밀번호는 예시에 안내한 32바이트 랜덤 hex 값으로 만든다. JWT는 별도로 생성한다. 새 데이터 볼륨에서 PostgreSQL 초기 SQL이 실행되고 API 시작 시 기존 멱등 마이그레이션이 적용된다.

Caddy는 DNS가 서버를 가리키고 80·443에 접근할 수 있으면 공개 인증서를 발급·갱신한다. IP 주소나 localhost만 설정한 경우 일반 브라우저가 신뢰하는 공개 도메인 인증서와 다르다. [Caddy HTTPS 조건](https://caddyserver.com/docs/automatic-https).

## 공개 주소에서 확인할 항목

실제 주소가 생긴 뒤 HTTPS 인증서, 로그인·샘플 생성, 업로드·다운로드, 스트리밍 질문, 정확한 샘플 합계 **690,200원**, 차트·저장·재접속, 공개 공유 이미지 응답을 확인한다. 로컬 검증이 이 공개 환경 검사까지 대신하지 않는다.

DB와 업로드 볼륨은 함께 백업해야 파일 카탈로그와 원본의 대응을 유지할 수 있다. 첫 공개 전 서버 스냅샷·복구 경로를 확인하고, 이후 업그레이드 전에도 백업한다. 기존 스키마에 변경이 적용된 뒤에는 이미지 버전만 되돌려 DB까지 복원됐다고 판단하지 않는다.

중지와 재시작은 같은 프로젝트 이름으로 수행한다. 다음 명령은 볼륨을 보존한다.

```bash
docker compose --env-file .env.public -p dataez-public \
  -f docker-compose.yml -f deploy/compose.public.yaml stop
docker compose --env-file .env.public -p dataez-public \
  -f docker-compose.yml -f deploy/compose.public.yaml up -d --wait
```

실사용 데이터가 들어간 환경에서 `down --volumes`를 사용하지 않는다. Lightsail 서버 비용은 Docker 컨테이너를 중지하는 것만으로 없어지지 않는다. 서버 폐기·보관 비용은 실제 리소스 정리 시 따로 확인한다.

## 로컬 사전 검증

`deploy/verify.py`는 별도 loopback 포트·Compose 프로젝트·DB와 볼륨을 생성한다. 로컬 Caddy CA를 해당 테스트 HTTP 클라이언트만 신뢰하며 OS 인증서 저장소는 바꾸지 않는다. 정상 종료·실패 시 자신이 만든 Compose 라벨을 확인한 뒤 임시 리소스를 정리한다. `.local-test/public-deploy/`에는 모델 키가 있는 환경 파일이 있으므로 공유하지 않는다.

```powershell
# API Python 의존성과 Docker가 설치된 개발 환경에서 실행
python deploy/verify.py --env-file D:/Github/DATAEZ/.env --live-llm
```

합성 샘플의 실제 임베딩과 모델 질문 1개를 호출한다. UI 시각 평가, 공개 인증서 발급, AWS VM 부하 검사는 이 도구의 범위 밖이다.

### 2026-09-11 결과

- 공개 설정 검사 **12개 통과**: 실제 Compose 병합에서 기존 개발 모드·공개 API 포트·localhost 설정이 남지 않음을 확인하고, HTTP·주소 불일치·개발 키·잘못된 DNS 이름·포트·비밀번호를 차단한다.
- 최종 Docker 이미지(Node 24, Next.js 16.3.4)로 **HTTPS 검사 22개 통과**. 실제 로그인 페이지 HTTP 응답·공유 이미지·CORS·API 준비 상태·샘플 원본 다운로드·다른 계정 접근 차단·정확한 690,200원·실제 모델 SSE·로그인 요청 제한을 확인했다.
- 컨테이너를 제거하고 같은 볼륨으로 다시 생성한 뒤 계정 로그인, 원본 바이트 해시, 지표 3개의 ID와 합계가 유지됐다. 인증서 CA도 유지되어 동일한 검증 클라이언트로 재접속했다.
- 모델 응답: 최초 SSE 프레임 **6.266초**, 전체 **8.672초**, 질문 1개·모델 호출 3회·24,185토큰. 질문 추정 비용 **$0.030130**은 저장소 가격표 기준으로 실제 청구액이 아니며 샘플 색인 임베딩 비용을 포함하지 않는다.
- `npm audit --omit=dev`의 기존 **5건 → 0건**, 전체 `npm audit`도 **0건**. 공개 npm 감사 요약을 별도로 보관했다.
- 최종 실행 ID: `public-check-20260910t165457z-06e7e735`. 기준 커밋 `8f65b36`에 배포용 변경을 적용한 작업 트리를 검사했으며 실제 파일 해시를 보고서에 기록했다. 검사 중 해당 파일이 바뀌지 않았고, 공개 보고서 저장 시에도 일치함을 확인했다.
- 초기 도구 시도는 Compose 프로젝트 이름의 대문자 때문에 기동 전에 중단됐다. 이름을 고친 후 사전 검증이 통과했고, 의존성 보완 후 새 이미지로 최종 검사를 다시 실행했다. 최종 성적에 앞선 실행을 합산하지 않는다.
- 생성한 테스트 컨테이너·네트워크·볼륨은 정리했다. 이 결과를 AWS 공개 배포나 실제 사용자 관찰 통과로 표시하지 않는다.

[최종 HTTPS 검사 JSON](evaluations/public-deployment/local-https-final.json) · [의존성 검사 요약](evaluations/public-deployment/dependency-audit.json).
