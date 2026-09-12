# DATA:EZ

**우리 가게 매출, 한눈에.**

여러 가게를 운영하는 소상공인이 흩어진 매출 파일과 현금 기록을 모으고, 자연어로 필요한 통계를 만들어 대시보드에 저장하는 서비스입니다. 저장한 통계는 같은 출처와 계산 기준으로 다시 계산할 수 있습니다.

[서비스 체험](https://dataez.vercel.app) · [포트폴리오 사례](docs/portfolio-demo/CASE_STUDY.md) · [영상·자막 안내](docs/portfolio-demo/VIDEO_RELEASE.md) · [전체 문서](docs/README.md)

![실제 DATA:EZ 대시보드 — 원본과 누적 장부의 일별 순결제액](docs/portfolio-demo/assets/phase-2-dashboard-dark.png)

실제 공개 웹·API·DB·LLM으로 검증한 화면입니다. 합성 매출 파일의 원본 합계는 **690,200원**, 거래 30,000원 추가 후 누적 장부 합계는 **720,200원**입니다. 합계는 집계표로 검증했으며, 원본 파일은 그대로 유지됩니다. [실행 기록과 라이트 화면](docs/portfolio-demo/ACCEPTANCE.md)

## 직접 체험하기

1. [공개 앱](https://dataez.vercel.app)에서 회원가입·로그인합니다.
2. **샘플 데이터로 시작**하거나 가게를 만들어 CSV/XLSX를 보관함에 올립니다.
3. 채팅에서 보관 파일을 선택하고 **파일 원본만 / 누적 장부 전체** 범위를 확인합니다.
4. 필요한 통계를 질문하고 그래프·집계표·SQL·기간·출처를 확인합니다.
5. 재계산 가능한 결과의 이름·단위·기간·갱신 주기를 검토한 뒤 대시보드에 저장합니다. 위젯을 이동·리사이징하고 새로고침할 수 있습니다.

촬영과 같은 조건을 사용하려면 [원본 CSV](samples/demo/portfolio-original.csv)와 [질문·기대값](docs/portfolio-demo/scenario.json)을 참고하세요. 기본 샘플 가게는 촬영용 데이터와 별개입니다. 파일을 처음 선택하면 원본 범위가 기본이며, 누적 범위는 장부에 연결된 파일에서 사용합니다.

**영상:** 제품 110초 · 기술 300초 · 반복 12초를 제작했습니다. [제작·재생 안내](docs/portfolio-demo/VIDEO_RELEASE.md)에 자막·대표 화면·검수 기록을 공개합니다. 영상 파일은 제작 환경의 로컬 산출물이며 아직 공개 호스팅하지 않았습니다. 저장소를 복제하는 것만으로 영상 마스터가 내려오지는 않습니다.

## 핵심 기능

| 영역 | 구현 범위 |
|---|---|
| 가게·매출·파일 | 계정별 여러 가게, 원본 보관·다운로드·미리보기, CSV/XLSX 매핑, 중복·충돌·취소 검토, 현금 입력 |
| 자연어 분석 | 관련 파일·스키마·문서 검색, 구조화된 지표 생성, 차트·정확한 집계표·실행 SQL |
| 저장 지표 | 단일/여러 장부 집계, 계산식, 명시적으로 선택한 여러 가게 비교, 정의 수정·이력·복원 |
| 대시보드 | 저장 전 미리보기, 중복 저장 방지, 배치 저장, 수동·매시간·24시간 재계산 |
| 화면 | ECharts, Spoqa Han Sans Neo, Charcoal + Blue, 다크·라이트·시스템 테마, 오른쪽 접이식 AI 채팅 |

주기 갱신은 이미 수집한 데이터를 다시 계산하며, PG의 새 거래를 수집하지 않습니다. 정상적인 저장 지표 재계산에는 LLM을 호출하지 않습니다. 정의 없는 정적 그래프는 결과 스냅샷으로 저장됩니다. [분석 범위와 저장 계약](docs/FILE_SCOPE_AND_FIRST_USE.md)

## 어떻게 구현했나

```text
보관 파일·장부 → 자연어 질문 → 구조화된 지표 정의
                                  ↓
                       권한·출처·계산 조건 검증
                                  ↓
                       SQL 집계 → ECharts·집계표
                                  ↓
                       정의 저장 → 같은 기준으로 재계산
```

LLM은 도구 인자와 지표 정의를 제안하고, 서버가 이를 검증해 SQL을 구성합니다. RAG는 관련 자료를 찾는 역할이고 숫자는 선택된 데이터에 대한 DB 집계로 계산합니다. 원본과 누적 장부의 구분은 출처와 저장 정의에 유지됩니다.

| 계층 | 현재 공개 배포 구성 |
|---|---|
| 웹 | Vercel · Next.js 16 / React 19 / TypeScript / Tailwind 4 |
| 그래프·배치 | Apache ECharts 6.1.0 SVG / react-grid-layout |
| API·모델 | Vercel Python FastAPI / OpenAI 도구 호출 / SSE |
| 인증 | FastAPI 자체 JWT 흐름 |
| DB·검색 | Supabase PostgreSQL / pgvector / 한국어 전문 검색 / RRF |
| 원본 | Supabase 비공개 Storage · 서명 URL 직접 업로드 · 완료 시 크기·해시 검증 |
| 정기 작업·제한 | Supabase Cron → 보호된 API / PostgreSQL 공유 요청 제한 |

현재 배포에는 AWS와 Redis가 없습니다. 로컬 `persistent` 프로필은 디스크 저장·상주 작업 루프·메모리 요청 제한을 사용할 수 있습니다. 공개 `serverless` 프로필은 DB에 작업 상태와 요청 횟수를 보존합니다.

[사례 문서](docs/portfolio-demo/CASE_STUDY.md)에서 구조화된 정의, 원본/누적 범위, 직접 업로드, Redis 제거의 이유와 제약을 설명합니다. [아키텍처](docs/ARCHITECTURE.md) · [배포 구조도 HTML](docs/portfolio-demo/architecture.html)

## 검증과 한계

2026-09-12 기록입니다. 서로 다른 검증 범위이므로 통과 수를 합산하지 않습니다.

| 확인 | 결과·근거 |
|---|---|
| 실제 공개 서비스 리허설 | 수정본에서 2회 연속 통과. 각 질문 2회·저장 2회·거래 추가·재계산·드래그·재접속·가게 전환. [Phase 2 기록](docs/portfolio-demo/phase-2-rehearsal.json) |
| API 회귀 | 525 passed / 260 skipped. DB 환경이 필요한 건너뛴 검사를 실제 DB 통과로 해석하지 않음. [검사 범위](docs/portfolio-demo/ACCEPTANCE.md) |
| 프론트엔드 | TypeScript, 워크스페이스 14개 검사, 다크/라이트 반응형 28개 화면 통과. [검사 범위](docs/portfolio-demo/ACCEPTANCE.md) |
| 영상 | 실제 촬영 후 모든 출력 전체 디코딩, 영상 3종 1배속 끝까지 재생. [제작·검수](docs/portfolio-demo/VIDEO_RELEASE.md) |

실제 PG 연동, 고객 사용성 관찰, 대규모 운영 부하는 후속 과제입니다. 합성 데이터로 확인한 결과를 사업 성과나 일반적인 LLM 정확도 보장으로 설명하지 않습니다. [이전 평가와 원시 근거](docs/README.md#검증-근거)

## 로컬 실행

Docker·Docker Compose와 모델 API 키가 필요합니다. 원본 저장은 로컬 디스크가 기본입니다.

```powershell
# 기존 .env는 보존합니다.
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# .env의 OPENAI_API_KEY를 설정한 뒤 실행
docker compose up --build
```

[웹 localhost:3000](http://localhost:3000)에서 회원가입·로그인할 수 있습니다. [API 문서](http://localhost:8000/docs) · [상태 확인](http://localhost:8000/health)

macOS/Linux에서는 `.env`가 없을 때 `cp .env.example .env`를 실행합니다. `.env.example`의 DB·JWT 값은 로컬 개발용입니다. 의존성·테스트·개별 실행은 [개발 안내](CONTRIBUTING.md), 환경변수는 [설정](docs/CONFIGURATION.md), 반복 체험은 [지속형 데모 안내](docs/DEMO_RUNBOOK.md)를 참고하세요.

## 라이선스

[MIT](LICENSE). 웹폰트·ECharts의 별도 라이선스와 NOTICE는 [폰트 출처](web/app/fonts/README.md), [디자인 자료 안내](outputs/frontend-design/README.md)에 있습니다.
