# DATA:EZ 첫 공개 데모 배포안

2026-09-11 · 배포 후보 브랜치 `codex/public-demo-deployment`.

**현재 상태: 로컬 배포 준비·검증 완료, 공개 서버 생성 비용·주소 확인 대기. 공개 클라우드 서버는 아직 생성하지 않았다.** Phase 3의 `9663f5f`와 브랜드의 `dbf6f0e`를 별도 배포 브랜치에 통합했다. 기존 작업 폴더의 미커밋 브랜드 변경은 건드리지 않는다. 사람의 사용성 관찰보다 공개 데모 준비를 먼저 진행한다.

## 권장 구성과 비용

현재 웹·API·PostgreSQL 구조를 유지하는 **AWS Lightsail 단일 서버**를 첫 후보로 삼는다. 서울 `ap-northeast-2`, Ubuntu 24.04 LTS(`ubuntu_24_04`), IPv4 포함 2GB/2 vCPU/60GB(`small_3_0`)의 표시 요금은 **월 최대 $12**다. 실제 AWS 읽기 전용 API로 해당 리전의 활성 번들과 블루프린트를 확인했다. 현재 연결 계정에서 서울 Lightsail 인스턴스와 Route 53 hosted zone은 조회되지 않았다. 다른 리전·외부 DNS까지 비어 있다는 의미는 아니다.

모델 API 사용료, 도메인 등록, 별도 스냅샷·전송 초과·세금은 위 서버 요금과 별도다. 무료 체험 자격을 확인하지 않았으므로 무료로 가정하지 않는다. 2GB는 소규모 합성 데모의 시작 후보이며 VM에서의 실제 메모리·부하는 생성 후 확인한다. 빌드 중 메모리가 부족하면 다른 환경에서 이미지를 빌드해 전달할 수 있다.

Google Cloud에서도 VM 한 대로 같은 구성을 운영할 수 있다. Cloud Run은 트래픽이 없을 때 인스턴스를 0으로 줄일 수 있지만, 현재 API 안에서 동작하는 색인 작업·지표 주기 갱신에는 최소 인스턴스 유지 또는 작업 구조 변경이 필요하다. 이번에는 이미 검증한 Compose 경로를 활용한다.

근거: [AWS 번들 요금](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html), [Lightsail 요금·추가 항목](https://aws.amazon.com/lightsail/pricing/), [Cloud Run 확장과 백그라운드 작업](https://docs.cloud.google.com/run/docs/about-instance-autoscaling).

## 배포 파일

- [공개용 Compose 추가 설정](../deploy/compose.public.yaml): 기존 `docker-compose.yml`에 덧붙여 API·웹의 직접 공개 포트를 제거하고 HTTPS 프록시를 추가한다.
- [Caddy 설정](../deploy/Caddyfile): `/api/*`, `/health`, `/ready`를 API에 전달하고 나머지는 웹에 전달한다. SSE 응답을 버퍼링하지 않으며 `/metrics`는 공개하지 않는다.
- [환경변수 예시](../deploy/.env.public.example), [설정 검사](../deploy/check.py), [격리 검증 도구](../deploy/verify.py).

프록시만 80·443을 공개한다. PostgreSQL·원본 파일·인증서 상태를 각각 영구 볼륨에 보관한다. API는 기존처럼 프로세스·복제본 1개이며, `APP_ENV=production`과 공개 주소에 맞는 CORS를 사용한다. Caddy가 전달하는 실제 클라이언트 IP를 신뢰하도록 설정하므로 로그인 요청 제한이 프록시 한 주소로 합쳐지지 않는다. API 포트는 직접 외부에 노출하지 않는다.

브라우저 API 주소와 공유 이미지 주소는 같은 `PUBLIC_ORIGIN`으로 빌드한다. 주소가 바뀌면 웹 이미지를 다시 빌드해야 한다. 웹 Docker 런타임은 지원 종료된 Node 20에서 Node 24 LTS로 변경했다. [Node 지원 현황](https://nodejs.org/en/about/previous-releases).

이미지 빌드 중 기존 의존성 경고를 확인해 Next.js와 `eslint-config-next`를 **16.3.4**로 올리고, 호환 범위의 간접 의존성을 잠금 파일에 갱신했다. 기존 16.1.6은 [Next.js의 AVIF 처리 보안 공지](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4)의 영향 범위였다. 수정 후 `npm audit --omit=dev`와 전체 `npm audit` 모두 알려진 취약점 **0건**이다. 이는 해당 시점의 npm 의존성 검사이며 OS·Python을 포함한 전체 시스템 보안 보증은 아니다.

## 서버 생성 후 실행

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
