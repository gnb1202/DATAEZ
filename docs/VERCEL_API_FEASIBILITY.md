# Vercel 무료 API 배포 적합성 검증

2026-09-11 · 검토한 코드: `b133c9e` · 판단: **조건부 진행 가능**

기존 Python 의존성과 앱 모듈은 실제 Vercel에서 빌드·로딩됐고, 한국어 분석·CSV 파싱·SSE 응답도 동작했다.
그러나 현재 API 전체를 설정 변경만으로 배포할 수 있다는 뜻은 아니다. 업로드와 작업 실행 방식의 수정이 필요하다.
월 고정 서버비 때문에 AWS/Lightsail 도입은 보류하고 **Vercel Hobby + Supabase Free**를 우선 검토한다.
AI 호출료는 별도이며, 무료 플랜 사용량 안에 들어가는지는 통합 이후 측정해야 한다.

후속 구현: [서버리스 실행 기반](SERVERLESS_FOUNDATION.md)을 구현하고 실제 로컬 DB로 검증했다.
아래 현재 코드 표는 적합성 조사 당시의 상태이며, 원격 Supabase 연결은 프로젝트 지정 대기다.

## 실제 확인한 범위

- 기존 공개 프론트 `dataez.vercel.app`의 프로젝트·환경변수·API 연결은 변경하지 않았다.
- 별도 임시 프로젝트 `dataez-api-feasibility-20260911`에서 실제 Vercel 배포를 수행했다.
- 커밋된 `api/app`, `requirements.txt`와 검증 진입점·설정만 추출했다. CLI 실제 업로드 목록 82개를 검사했다.
- 검증 진입점은 DATA:EZ 앱을 import만 한다. 원래 86개 라우트를 외부에 연결하거나 lifespan을 실행하지 않는다.
- 실제 DB·Storage·LLM 자격 증명을 전달하지 않았다. 합성 데이터만 사용했다.
- 실제 클라우드 검사 6개가 통과했고, 종료 후 임시 프로젝트와 배포를 삭제했다.
- AWS 리소스, Supabase 프로젝트, 유료 플랜은 생성하지 않았다.

[클라우드 검사 결과](evaluations/vercel-api/cloud-probe.json) · [Linux 측정 결과](evaluations/vercel-api/linux-probe.json) · [재현 방법](../scripts/vercel-audit/README.md)

| 측정 | 결과 | 해석 |
|---|---|---|
| Linux 설치 패키지 크기 | 401,012,657 bytes, pyc 제외 338,358,586 bytes | Docker 전체 이미지 크기와 다르며 Vercel 최종 번들 크기도 아님 |
| Vercel 빌드 | READY, Python 3.12.13 | 빌더가 최적화 전 322.79MB를 보고했고 실제 배포 성공. 최종 바이트 크기는 미측정 |
| Vercel 앱 import | 2.167초, 86개 라우트 로딩 | DB 초기화·마이그레이션을 포함한 서비스 기동 시간은 아님 |
| Vercel 한국어 분석 + CSV 1,000행 | 4.075초, 합계 12,000,000 검증 | 이 호출의 프로세스 최대 RSS 663,420,928 bytes |
| Vercel SSE | 3개 이벤트 수신 | 실제 LLM 스트림이나 300초 장기 연결 검사는 아님 |
| Vercel 요청 본문 | 1,000,000 bytes 성공 / 6,000,000 bytes 413 | API 본문 업로드 경로의 실제 제약 재현 |
| Linux CSV 100,000행 | 3,500,039 bytes, 파싱 2.527초 | 행 수·금액 합계 검증. DB 쓰기·인덱싱 제외 |
| Linux XLSX 10,000행 | 178,680 bytes, 파싱 1.446초 | 행 수·금액 합계 검증. 복잡한 임의 엑셀을 대표하지 않음 |

Linux 검사는 1 CPU / 2GiB 메모리 제한, 네트워크 차단, 읽기 전용 컨테이너에서 실행했다.
설치된 직접 의존성 18개의 버전 조건을 현재 requirements와 대조했다. 이 제한이 실제 Vercel 성능과 같다는 의미는 아니다.
로컬과 클라우드의 전이 의존성은 달라질 수 있으며 결과 JSON에 각 버전을 기록했다.

기존 실제 LLM 평가의 본 평가 30문항은 4.468~13.156초, 별도 10문항은 5.140~7.891초였다.
이는 [이전 로컬 평가](evaluations/unseen-v1/main-final.json)의 관측치이며 Vercel 지연·최악 실행 시간 보장이 아니다.

## 그대로 배포하기 어려운 지점

| 항목 | 현재 코드 | 필요한 변경 |
|---|---|---|
| 파일 업로드·원본 다운로드 | 최대 20MiB를 API 본문으로 전달, 채팅 다중 첨부도 multipart | 브라우저↔비공개 Storage 직접 전송. API는 파일 ID와 메타데이터를 받도록 변경 |
| 파일 영구 보관 | 기본값 local, 앱 import에서 디렉터리 생성 | Supabase Storage의 S3 호환 경로 사용. `/tmp`는 임시 처리만 허용 |
| 백그라운드 실행 | lifespan에서 지표·색인·정리 루프를 create_task로 시작 | 요청 단위의 제한된 작업으로 분리. 함수 종료 뒤에도 루프가 계속 돈다고 가정하지 않음 |
| 정기 통계 | 저장 옵션은 수동·1시간·1일, 워커가 15초마다 확인 | Supabase Cron의 HTTP 호출 등으로 due 작업을 실행. Vercel Hobby Cron만으로 1시간 옵션 충족 불가 |
| DB 연결과 초기화 | 프로세스마다 min 2 / max 10 풀, 시작 때 DDL·정리 | 작은 연결 풀, transaction pooler 호환 설정, 배포 시 별도 마이그레이션 |
| AI 실행 시간 | 최대 25회 반복, 개별 호출 60초와 재시도 3회, 전체 시간 제한 없음 | 전체 요청 마감 시간과 남은 시간 기반 개별 호출 제한. 시간 초과 시 결과를 저장 성공으로 표시하지 않음 |
| 요청·AI 비용 제한 | 프로세스 메모리 카운터 | 여러 인스턴스와 재기동에 공통인 DB 기반 카운터·원자적 사용량 예약 |

관련 코드: [lifespan](../api/app/main.py), [파일 처리](../api/app/data_import.py), [저장소](../api/app/storage.py),
[색인 작업](../api/app/index_jobs.py), [지표 스케줄러](../api/app/metric_scheduler.py), [DB 풀](../api/app/db.py),
[요청 제한](../api/app/rate_limiter.py), [모델 클라이언트](../api/app/openai_clients.py).

색인 작업은 이미 DB에 상태·lease·재시도를 보관하고 지표 갱신도 행 잠금을 사용한다. 이 구조는 재사용할 수 있다.
다만 색인 lease가 600초이고 함수 상한은 300초이므로 중단·회수·재시도와 작업 크기를 함께 조정해야 한다.
단순히 worker 플래그를 모두 끄면 파일이 검색되지 않고 예약 갱신도 사라지므로 배포 완료로 처리하지 않는다.

## 다음 구현 순서와 완료 조건

1. **API 실행 기반:** Vercel용 진입점, Python 버전 고정, 작은 DB 풀·prepared statement 비활성화,
   마이그레이션 분리, Supabase 비공개 데이터 접근 구성. 새 인스턴스 여러 개의 동시 로그인·읽기를 검증한다.
   현재 인증은 자체 JWT이므로 Supabase Auth 전환은 전제하지 않는다. Data API를 쓰지 않는 앱 테이블은 노출을 차단하고,
   노출 스키마에는 RLS를 적용한다. 서비스 비밀키를 브라우저에 전달하지 않는다.
2. **파일 전송:** 소유권을 검증한 짧은 유효기간의 업로드 URL과 서버 생성 객체 키를 발급하고, 완료 시 크기·형식·소유권을 검증한다.
   재사용 가능한 업로드 URL로 확정 원본이 바뀌지 않도록 임시 객체에서 확정 객체로 전환하는 절차가 필요하다.
   일반 업로드·장부 추가·가져오기·채팅 첨부·원본 다운로드를 모두 확인한다. 목표는 기존 20MiB 계약 유지이며,
   별도 제품 결정 없이 파일 한도를 낮추지 않는다.
3. **작업·예산:** 색인과 정리 작업을 제한된 배치로 실행하고 중단 후 재시도를 검증한다.
   지표의 1시간·1일 옵션은 Supabase Cron 등 외부 호출로 유지하고 실행 지연 허용 범위를 명시한다.
   자체 인증을 검증하는 작업 endpoint, 중복 실행 잠금, 전체 AI 마감 시간과 계정별 공유 예산을 갖춘다.
   Redis를 다시 도입할 필요는 없다.
4. **실제 통합:** 원격 Supabase에서 두 계정 격리, 파일 왕복·재접속, AI→SQL→차트→저장,
   예약 갱신, 작업 중단·복구를 검증한다. 이 단계에서 실제 LLM 호출 및 무료 사용량을 측정한다.

## 플랜 제약과 비용 판단

- Vercel Hobby/Fluid: 함수 최대 300초, 메모리 2GB, Python 표준 번들 500MB, 본문 4.5MB 제한.
  Python 스트리밍은 지원한다. Large Functions 베타는 별도 기능이며 이번 검증에서 최종 번들 방식을 식별하지는 않았다.
- Hobby 월 포함량: Active CPU 4시간, Provisioned Memory 360GB-hours, 함수 호출 100만 회.
  비상업적 개인 프로젝트용이며 무료 한도 초과는 서비스 제한으로 이어질 수 있다.
- Vercel Hobby Cron은 작업별 하루 1회, 시간 정확도는 시간 단위다. 기존 시간별 갱신의 대체 수단이 아니다.
- Supabase Free는 DB 500MB·Storage 1GB이며 비활동 시 일시 중지될 수 있다. 원격 스키마·벡터·파일을 옮긴 후 실제 용량을 확인한다.
- 장시간 AI 대기, 반복 색인, 콜드 스타트도 사용량에 영향을 준다. 임시 검사 통과만으로 월 사용량을 보장하지 않는다.
- 기존 OpenAI 호출료는 별도다. Bedrock 전환은 이번 배포 검증 범위에 포함하지 않는다.

공식 근거 (2026-09-11 확인): [Vercel 함수 제한](https://vercel.com/docs/functions/limitations),
[Python 런타임](https://vercel.com/docs/functions/runtimes/python), [Hobby 플랜](https://vercel.com/docs/plans/hobby),
[Cron 제한](https://vercel.com/docs/cron-jobs/usage-and-pricing), [Supabase DB 연결](https://supabase.com/docs/guides/database/connecting-to-postgres),
[Storage 서명 URL 호환성](https://supabase.com/docs/guides/storage/s3/compatibility),
[Supabase Cron](https://supabase.com/docs/guides/cron), [Supabase Free](https://supabase.com/pricing).

Supabase changelog도 확인했다. 확장 버전 고정 관련 변경은 향후 마이그레이션에서 실제 설치 버전을 점검해야 하며,
이번에는 원격 스키마나 확장을 변경하지 않았다.
