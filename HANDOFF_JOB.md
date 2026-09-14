# DATA:EZ — 다음 세션 작업 인계

> **후속 완료 알림 (2026-09-14):** [PR #15](https://github.com/gnb1202/DATAEZ/pull/15)에서 문서 작업을 main·원격에 통합했고 통합 커밋의 CI와 production 배포를 확인했다. 이 파일의 본문은 이번 세션 시작 전의 인계 스냅샷으로 보존한다. 아래의 모바일/PDF 미검증 상태와 Git 통합 대기 상태를 최신 상태로 해석하지 않는다. 후속 검증 결과는 [현재 상태](docs/CURRENT_STATUS.md), [제출 자료 검수](docs/portfolio-demo/SUBMISSION_QA.md), [새 실행 기록](docs/evaluations/submission-20260914/verification.json)을 따른다. ZIP 해제 HTML 직접 열기와 브라우저 자체 인쇄는 계속 미확인이다.

작성 기준: **2026-09-14, Asia/Seoul**. 이 문서는 대화 요약과 다음 작업의 시작점이다. 실행 증거 원문은 아래 연결된 문서를 따른다. 과거 검증 결과를 새 세션에서 직접 수행한 검사로 보고하지 않는다.

## 0. 다음 세션에서 먼저 할 일

1. 이 문서와 `docs/CURRENT_STATUS.md`를 읽는다.
2. `git status --short --branch`, `git log -5 --oneline`, 원격 상태를 확인한다. 아래 상태는 작성 당시 기준이다.
3. 바로 전 사용자에게 제안했던 후속은 **이번 문서 작업 main 통합·푸시 → 제출 파일의 남은 검증 → 실제 지원 공고에 맞춘 설명** 순서다. 사용자는 새 세션으로 옮기기 위해 이 인계 파일 작성을 요청했다. 이번 턴에는 통합·푸시나 추가 QA를 수행하지 않았다.
4. 사용자가 이어서 진행하라고 하면 1·2번 마무리를 우선한다. 기능 확장, 디자인 재개편, 인프라 이전을 임의로 시작하지 않는다.

새 세션용 시작 요청 예시:

> `HANDOFF_JOB.md`를 읽고 현재 Git 상태와 연결된 증거를 확인해주세요. 우선 제출용 한 페이지의 PDF/모바일 검증과 전달 파일의 남은 확인을 진행하고, 필요한 수정만 반영한 뒤 이번 문서 작업을 main·원격에 통합해주세요. 과거 검사와 이번 검사를 구분하고, 차단되거나 실행하지 못한 검사는 통과로 표시하지 마세요.

## 1. 프로젝트 목적과 확정된 제품 방향

**DATA:EZ는 여러 가게를 운영하는 소상공인이 흩어진 매출 파일과 현금·카드 기록을 모으고, 자연어로 통계를 만들어 대시보드에 저장·재계산하는 서비스다.** 현재 우선순위는 실서비스 규모 확장보다 공개 체험·포트폴리오 시연이다.

- 대상: 한 사용자 아래 여러 가게. 가게별 파일·장부·지표의 범위와 소유권을 구분한다.
- 핵심 동선: 로그인 → 가게 → 파일 저장/선택 → 원본 또는 누적 범위 선택 → 질문 → 도구 호출 → 집계표·SQL·차트 확인 → 설정 검토 → 지표 저장 → 재계산.
- 자연어/LLM 메타프로그래밍의 현재 구현은 **구조화 도구 인자와 지표 정의를 서버가 검증하고 SQL로 구성하는 방식**이다. 임의 SQL/Python을 자유롭게 실행하는 범용 환경으로 설명하지 않는다.
- RAG는 관련 자료·파일·스키마 탐색을 돕는다. 정확한 금액은 DB 집계로 계산한다. 파일을 명시적으로 선택한 대표 시연을 RAG 검색 품질의 증거로 쓰지 않는다.
- 원본 파일 범위는 업로드 당시 행을 보존한다. 누적 범위는 연결 장부에 반영된 추가 거래를 포함한다.
- 일반적인 저장 지표 재계산에는 LLM을 다시 호출하지 않는다. 정의·출처·기간·통화를 보존한다.
- 대시보드는 드래그·리사이즈 및 배치 저장을 지원한다. AI 채팅은 오른쪽에서 접고 펼친다.
- 실제 PG 연동·자동 PG 수집은 후속이다. 현재 사용자의 요청으로 우선순위에서 제외했다.

### 디자인 결정 — 다시 선택받지 않을 것

- **Spoqa Han Sans Neo** 확정. 저장소 폰트와 라이선스를 재사용한다.
- **Charcoal Blue** 확정. 다크가 주 테마이고 라이트도 지원한다.
- OpenAI Platform처럼 왼쪽 메뉴·넓은 작업 영역·오른쪽 접이식 채팅을 참고했다.
- 그래프는 현재 구현/평가에서 **ECharts**를 사용한다. 의존성에 다른 라이브러리가 있다고 모든 차트가 그 엔진이라고 단정하지 않는다.
- 로그인은 승인받은 시안과 **저채도 사장님/PC·POS 모니터 이미지**를 사용한다. 헤드라인은 “우리 가게 매출, 한눈에.”다.
- 09-13 앱 색상 보정을 수행했다. 09-12 캡처·영상은 그 이전 색상이며 자동 동기화되지 않는다.
- 브랜드 인계는 별도 `docs/brand/BRAND_HANDOFF.md`가 있다.

## 2. 환경과 Git 상태

| 항목 | 작성 당시 상태 |
|---|---|
| 작업 디렉터리 | `D:\Github\DATAEZ` |
| OS / Shell | Windows / PowerShell |
| 저장소 | https://github.com/gnb1202/DATAEZ — 공개 |
| 현재 브랜치 | `codex/portfolio-submission` |
| HEAD | `7ba4f00` — `docs: prepare portfolio submission and verify public post-merge flow` |
| 직전 main 기록 | `ef934385e1c2126f85007bcf37f35489129cef16` — main 통합 상태 기록 |
| 그 전 통합 | `3524d22df4e3e419bd5cdc63190b84fdfecf352c` — PR #14 merge |
| 이번 시작 시 작업 트리 | clean. 이 `HANDOFF_JOB.md` 작성은 그 이후이며 아직 커밋하지 않음 |

**`7ba4f00`은 로컬 커밋이며 아직 main 통합·원격 푸시하지 않았다.** 원격 main이 ef93438과 같다는 것은 직전 통합 확인 당시 결과다. 새 세션에서는 fetch/조회로 갱신한다. 기존 사용자 변경을 덮어쓰거나 reset하지 않는다.

이전 [PR #14](https://github.com/gnb1202/DATAEZ/pull/14)는 이미 통합됐다. 보존된 주요 커밋은 다음과 같다.

- `d04486f`: 품질 평가·대화 관측
- `18fa08a`: 색상 보정
- `853bb9e`: 문서 사실관계·포트폴리오 자산

## 3. 배포 구성과 확인 범위

- 공개 웹: https://dataez.vercel.app/
- 공개 API: https://dataez-api.vercel.app/
- 구성: **Vercel Next.js 웹 + Vercel FastAPI + Supabase PostgreSQL/pgvector·비공개 Storage·Cron + OpenAI**.
- 인증은 **FastAPI 자체 JWT**. Supabase Auth로 설명하면 안 된다.
- Redis 의존성은 배포·데모를 단순화하기 위해 제거했다. 요청 한도와 작업 상태는 DB를 통해 공유한다.
- 현재 배포에 AWS/Lightsail/Bedrock/S3는 없다. 과거 대화에서 검토만 한 구성을 구현으로 쓰지 않는다.
- Cron은 기존 데이터의 유지보수·지표 재계산이며 PG 자료 수집이 아니다.
- 저장소 직접 업로드와 완료 검증이 있고 현재 상한은 문서상 20MiB다. 변경 시 설정·코드와 대조한다.

09-14 웹 커밋 ef93438의 Vercel 성공 상태를 확인했다:
https://vercel.com/gnb1202-navercoms-projects/dataez/97ZiNAAJtCLcaDh49ry6KmGNUGJj

API의 기존 기록은 배포 `dpl_3VyHSr7b5kB1aSCGRCfxTDr31d8T`, 릴리스 `quality-20260913-17ea846c6906`이다. 포트폴리오 자료 작업에서 API 재배포·DB 스키마 변경은 하지 않았다. 이 식별자를 실시간 최신 상태로 간주하지 않는다.

사용자는 Vercel CLI 로그인과 Supabase 연결을 이전에 완료했다. 새 세션에서 인증 유효 여부는 확인하되 비밀 값을 출력하지 않는다. 기존 설정이 있는데 계정 생성·프로젝트 생성·관리자 권한 부여를 다시 하지 않는다.

## 4. 완료된 검증과 정직한 해석

### A. 09-12 포트폴리오 QA·영상

- 합의된 Phase 5 범위: 첫 사용, 핵심 분석, 저장·재계산, 권한, 모의 실패 복구, 화면, 문서·영상 전달.
- 당시 필수 검사 통과, 해당 범위 미해결 P0/P1 없음. 이후 모든 변경이 자동 재검증된 것은 아니다.
- 대표 원본: **690,200원·8행**. 준비 API로 거래 **30,000원 1회** 추가 후 누적 **720,200원·9행**. 원본 해시와 범위 보존.
- 수정 전 정적 선그래프와 재계산 막대가 중복 생성된 지침 충돌을 발견했다. `preview_metric` 경로와 차트 정의를 정리하고 새 가게에서 전체 흐름 2회 연속 통과를 확인했다.
- 근거: `docs/portfolio-demo/FINAL_QA.md`, `phase-5-qa.json`, `ACCEPTANCE.md`, `phase-2-rehearsal.json`.
- 영상: 제품 110초, 기술 300초, 반복 12초. 실제 공개 서비스 촬영, 한국어 자막, 무음. 파일 선택 경로를 촬영했다.
- 로컬 마스터: `output/portfolio-demo/`. 기존 영상 ZIP: `output/portfolio-demo-delivery.zip`.
- 영상은 Git에 포함되지 않으며 공개 영상 URL도 없다. Git 복제로 영상까지 받는다고 안내하지 않는다.
- 영상/폰트/자막 검증: `docs/portfolio-demo/VIDEO_RELEASE.md`, `phase-3-*.json`.
- 촬영용 계정·가게·파일, 과거 QA 자료를 삭제하거나 초기화하지 않는다. 기존 `prepare.py check`는 촬영 전 8행·위젯 0개 조건이며 촬영 완료 상태 검사로 바꾸지 않는다.

### B. 09-13 실제 모델 24문항 평가

- `docs/AGENT_QUALITY_PIPELINE.md`와 `scripts/agent-quality/README.md`가 기준이다.
- 질문: `samples/agent-quality-v1/questions.json`.
- 동일 개발 회귀셋에 실제 모델 24문항씩 두 실행: 수정 전 **22/24**, 수정 후 **24/24**. 총 48질문이며 실패한 질문을 몰래 반복해 좋은 응답만 고르지 않았다.
- 당시 worker `gpt-5.4`, router `gpt-5.4-nano`. 이는 기록된 평가 설정이지 현재 모든 배포의 모델을 재조회한 결과는 아니다.
- 도구 계약, 지표 의미, 필터·범위, 독립 Decimal 집계 셀/SQL, 차트 수·형태·축·값·정의, ECharts SVG를 검사한다.
- 설명 6문항은 **Codex의 실제 근거 검토**다. 독립 사람 평가·블라인드 LLM judge·모든 자연어 질문 정확도 100%라고 쓰지 않는다.
- 프롬프트 수정: Q22의 미지원 환율 환산 안내, Q24의 같은 파일 원본/누적 동시 선택 안내를 실제 기능 한계에 맞췄다 (`api/app/library_agent.py`).
- 날짜 표현 동등성 때문에 grader도 v1→v3 보정했다. 독립 PostgreSQL 날짜 경계 실험 후 저장된 응답을 재채점했으며 이 내역을 감추지 않는다.
- 결과: `docs/evaluations/agent-quality-v1/baseline/`, `after/`, `date-boundary-control.json`, `first-grader-v1.json`.
- 이 회귀셋은 프롬프트 개선에 사용했다. 새로운 holdout 일반화 성능이 아니다. 후속으로 **미사용 질문·파일을 분리한 평가셋**이 제안됐지만 아직 시작하지 않았다.

### C. 대화 품질 관측 — 이미 구현·배포됨

- 문서: `docs/CHAT_QUALITY_OBSERVABILITY.md`.
- 기존 `messages`에 질문·답변·선택 파일·도구/차트 자료를 저장한다. 긴 도구 출력은 기존 3,000자 제한을 유지한다.
- `quality_runs`: 실행/대화/메시지 연결, 상태, 시간, 모델·관련 코드 버전. `messages.usage.call_details`: 호출별 사용량·추정 비용. `message_feedback`: 답변당 평가 1개 갱신.
- `completed`는 실행 완료이지 정답 판정이 아니다. failed/cancelled/unconfirmed를 구분하고 관측 쓰기 실패 때 분석을 재실행하지 않는다.
- 지정 관리자는 설정 및 계정 → 대화 품질 검토(`/quality`)에서 근거 검토, 실패 분류, 합성 후보 작성/내보내기를 할 수 있다.
- 사용자 지정 계정은 이미 가입·관리자 연결됐다. 권한은 서버의 `QUALITY_ADMIN_USER_IDS`에 자체 인증 사용자 UUID로 지정한다. 이메일만으로 권한을 부여하지 않는다. 기존 지정 계정 외에 임의로 승격하지 않는다.
- 공개 검증: `docs/evaluations/chat-quality-release/deployment.json`, `admin-verification.json`.
- 관리자 연결 당시 실제 API 검증은 짧은 서버 서명 토큰을 메모리에서만 사용했다. 관리자 브라우저 로그인 자동화 검증으로 표현하지 않는다. 사용자는 직접 로그인해 화면을 확인했다고 말했다.
- 회귀 편입: 관리자 합성 후보 + 수동 독립 기대값/계약 → `scripts/agent-quality/promote.py` → 별도 검증. 자동 학습·자동 개인정보 제거 시스템은 아니다.
- 보관 한계, 90일 TTL의 실행 조건, 강제 종료 시 사용량 누락 가능성은 원문을 읽는다. 새 개인정보·보안 보장을 만들어내지 않는다.

### D. 09-14 main 통합 검사 — 이미 완료

- 로컬 API **545 passed / 268 skipped**, 평가 도구 **41 passed**, 웹 빌드 통과.
- PR #14 원격 CI: API·웹·Docker 빌드, Agent Quality offline, 실제 임시 PostgreSQL 관측 **26 passed**.
- 유료 live job은 의도적으로 skipped. 유료 CI 평가 secret 설정/실제 원격 live 실행은 후속이다.
- 검사 수는 겹친다. 합산하지 않으며 skipped를 DB 검사 통과로 바꾸지 않는다.
- 당시 로컬 Docker Desktop이 타임아웃됐다. 원격 PostgreSQL CI가 별도 DB 근거다. Docker 초기화·볼륨 삭제로 해결하려 하지 않는다.
- 근거: `docs/evaluations/integration-20260914/verification.json`.
- 로컬 빌드 도구 버전과 package.json/원격 설치 버전은 다를 수 있다. 당시 Next 16.1.6 로컬 빌드 기록을 현재 의존성 명세로 쓰지 않는다.

### E. 09-14 통합 후 공개 UI 확인 — 바로 전 작업에서 완료

근거: `docs/evaluations/post-merge-20260914/verification.json`, `oracle.json`.

- Codex 인앱 브라우저, 새로운 합성 계정으로 실제 UI 가입.
- **샘플 데이터로 시작 버튼**으로 가게·파일을 만들고 원본 선택. 이번에는 수동 CSV 업로드를 다시 하지 않았다.
- 실제 모델 질문 **정확히 1회**, 자동 재시도 없음. 전체 기간, `paid_at` 일별 `amount` 합계, 음수 취소 차감, KRW 선그래프, 재계산 가능, 아직 저장하지 말라는 요청.
- 단일 선그래프, 정확한 집계표, SQL, 저장 설정 미리보기를 확인했다.
- 일별 값: 09-01 **164,500**, 09-02 **190,000**, 09-03 **139,800**, 09-04 **195,900**. 합계 **690,200**.
- `api/app/sample_workspace.py`의 CSV literal을 AST로 읽어 Python Decimal로 독립 계산했다. 모델 문장을 정답으로 삼지 않았다.
- “통합 확인 · 원본 일별 매출” 저장 → 로그아웃/재로그인 → 위젯 **1개**, 원본/전체 기간/KRW/수동 유지 → 재계산 버튼 1회 → 같은 정확한 일별 값 확인.
- UI 재계산 시각: **2026-09-14 17:20:08 KST**. 수집된 브라우저 오류 0개. 끝에 로그아웃했다.
- 합성 자료는 보존했다. 비밀번호는 브라우저 런타임에서만 생성·사용했고 이 문서나 공개 기록에 없다. 다음 세션에서 해당 계정 재로그인이 가능하다고 가정하지 않는다.
- 이 검사는 전체 Phase 5/24문항/권한/장애/반응형 재검사가 아니다. 원시 화면 녹화가 아닌 당시 브라우저 관측 기록과 독립 oracle 기반 영수증이다.

## 5. 이번 로컬 커밋 7ba4f00의 산출물

### 사용자가 볼 문서

- `docs/portfolio-demo/PORTFOLIO_GUIDE.html`: 기존 소개 HTML에 품질 평가·관측·관리자 검토→합성 회귀 흐름 추가. 직무 선택, 구조도, 원본/누적 비교, 면접 설명, 이력서 복사, 다크/라이트.
- `docs/portfolio-demo/SUBMISSION.html`: 제출용 한 페이지. 문제·해결, 기술 판단 3가지, 근거·한계, 구성·기여, 인쇄/PDF 버튼.
- `docs/portfolio-demo/SUBMISSION.md`: 이력서 문장, 직무별 강조, 3분 설명 순서.
- `README.md`, `docs/README.md`, `docs/CURRENT_STATUS.md`: 새 자료 및 별도 공개 확인 기록 연결.
- `output/portfolio-demo/submission-20260914.zip`: 로컬 전달 ZIP. Git ignore 대상. 약 1.04MiB. 영상 미포함.

ZIP에는 2개 HTML, 제출 MD, 이번 공개 확인 JSON·oracle, READ_ME가 들어 있다. HTML의 폰트·이미지·기존 Archify는 내장돼 있다. 외부 근거 링크는 인터넷이 필요하다. 새 공개 확인 링크는 상대 경로이며 ZIP도 그 디렉터리 구조를 보존한다.

### 생성 소스 / 검증 기록

- `scripts/portfolio-demo/portfolio-guide.template.html`
- `scripts/portfolio-demo/submission.template.html`
- `scripts/portfolio-demo/build-portfolio-guide.py`
- `scripts/portfolio-demo/package-submission.py`
- `docs/portfolio-demo/portfolio-guide-receipt.json`
- `docs/portfolio-demo/submission-package-receipt.json`
- `docs/evaluations/post-merge-20260914/artifact-checks.json`
- 과거 가이드 영수증 보존: `docs/evaluations/post-merge-20260914/previous-guide-receipt-20260913.json`.

수정은 템플릿에 반영하고 빌더로 생성한다. 생성 HTML만 고치면 다음 빌드에서 사라진다.

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/portfolio-demo/build-portfolio-guide.py
python scripts/portfolio-demo/package-submission.py
```

주의:

- 가이드 빌더는 `.local-test/portfolio-guide-archify-receipt.json`과 `.local-test/portfolio-guide-architecture.html`을 필요로 한다. 이 두 파일은 기존 로컬에 있었지만 Git에 없다. 새 clone에서는 바로 재빌드되지 않을 수 있다.
- 빌더는 Archify artifact SHA와 `docs/portfolio-demo/architecture.json` SHA, 9개 검증 통과를 확인한다. 해시 검사를 우회하지 않는다. 기존 검증된 구조도를 변경 없이 재사용했다.
- 생성된 HTML은 로컬 Archify 파일이 없어도 열 수 있다. 필요 시 관련 스킬/기존 검증 자료를 통해 재생성한다.
- 빌더를 다시 실행하면 visual_review가 pending으로 덮어써진다. 변경 후 실제 검증을 하고 새 해시와 함께 갱신한다. 과거 검수 문구를 그대로 새 파일에 옮겨 통과 처리하지 않는다.
- 패키징은 allowlist만 넣고 새 임시 폴더에 해제해 HTML/JSON 해시와 ZIP CRC를 대조한다. 제출 MD에서 번들 밖 상대 링크는 공개 GitHub 링크로 변환한다.
- ZIP 재생성도 `browser_portability_review`를 pending으로 만든다. 실제 수행 여부에 따라 기록을 복구한다.
- `git diff --cached --check`는 새 SUBMISSION.html의 **원문 Spoqa 라이선스 끝 공백 1개**를 보고했다. 라이선스 텍스트 그대로 보존했고 artifact-checks에 명시했다. 이를 앱 오류로 설명하지 않는다.

## 6. 남아 있는 검증 — 완료로 쓰지 말 것

| 대상 | 완료 | 아직 확인하지 못한 부분 |
|---|---|---|
| 상세 가이드 | 인앱 브라우저 1280×720 다크/라이트 품질 섹션, 직무 전환, 내장 구조도, 390×844 에뮬레이션 가로 넘침 없음 | 전체 접근성 재검사, 실제 모바일 기기, 인쇄 페이지 분할 |
| 한 페이지 HTML | 데스크톱 타이포/내용/가로 넘침/가이드 링크 | **모바일 실제 적용 확인**, **PDF/A4 한 장 분량 검증** |
| 전달 ZIP | allowlist, CRC, 새 임시 폴더 해제, HTML/JSON 해시 동일 | **압축 해제본을 브라우저로 직접 열기** |
| 정적 링크 | 로컬 파일·GitHub 저장소 경로 존재, anchor/ID, placeholder 없음, 내장 asset 확인 | 모든 외부 URL의 HTTP 상태 전수 검사 |

한 페이지의 모바일 검사를 시도했으나 viewport override가 그 탭에 적용되지 않아 실제 관측은 1280폭이었다. 통과로 기록하지 않았다. 브라우저 문서의 현재 탭/viewport 동작을 확인하고 **실제 innerWidth와 화면**을 대조해야 한다.

**브라우저 보안 차단 기록:** 압축 해제본의 `file:///.../SUBMISSION.html` 직접 열기가 브라우저 URL 정책으로 거절됐다. 도구는 같은 결과를 다른 브라우저/우회 경로로 달성하지 말라고 명시했다. 해당 검사 통과를 위해 임의 우회를 시도하지 않는다. 정책이 지속되면 직접 열기는 사용자 확인 항목으로 남기고, 기존 workspace HTTP 렌더 확인·추출 해시 확인과 구분해 보고한다. 앞선 세션의 기존 workspace HTTP 확인을 압축 해제본 실행으로 바꾸어 쓰지 않는다.

당시 압축 해제 위치는 `C:\Users\PC-CA\AppData\Local\Temp\dataez-submission-8hg647vd`였다. 임시 경로가 남아 있다고 가정하지 않는다. 비밀 자료가 포함된 경로는 아니다.

## 7. 미리보기와 필요한 실행 명령

기존 3131/3132/3133/3134/3136 등은 여러 단계에서 사용한 포트다. 사용자의 현재 탭 `http://127.0.0.1:3131/`가 최신 앱/가이드라는 보장은 없다. 서버 생존과 문서 루트를 확인한다.

이번 가이드의 올바른 로컬 서버 루트는 **docs 전체**다. 가이드 파일 디렉터리만 serve하면 `../evaluations/` 링크가 404가 된다.

```powershell
python -m http.server 3137 --bind 127.0.0.1 --directory docs
# http://127.0.0.1:3137/portfolio-demo/SUBMISSION.html
# http://127.0.0.1:3137/portfolio-demo/PORTFOLIO_GUIDE.html#quality
```

직전 세션은 위 서버와 이전 3136 서버를 시작했다. 도구 세션 ID나 브라우저 변수는 다음 세션에서 유효하다고 가정하지 않는다. 사용 중인 포트를 무차별 종료하지 않는다.

관련 검사 명령은 실제 수정 범위에 맞춰 선택한다. 이번 커밋은 앱 코드가 아닌 문서/빌드·패키징 스크립트 변경이다.

```powershell
python scripts/agent-quality/run.py validate
python -m pytest scripts/agent-quality -q
python -m pytest api/tests -q
npm run build --prefix web
```

- 실제 DB 검사는 반드시 별도 테스트 DB에 수행한다. 공개 DB를 임시 fixture/테이블 정리에 사용하지 않는다.
- 실제 모델 평가는 Docker와 키가 필요하며 비용이 발생한다. 패키지 검수나 Git 통합만으로 유료 모델 24문항을 재실행할 필요는 없다.
- `live --suite smoke`는 6문항, `live --suite full`은 24문항. 원문 실행 지침부터 읽는다.
- 이미지/영상/폰트 등 binary 변경이 없다면 과거 검증에 해시로 연결하고 전체 영상 렌더·디코딩을 불필요하게 반복하지 않는다.

## 8. 후속 작업 권장 순서와 완료 기준

### 우선: 제출 자료 마감과 통합

1. 한 페이지 모바일·PDF 인쇄 결과를 확인하고, 잘림이나 페이지 초과가 있으면 템플릿만 필요한 만큼 수정한다.
2. ZIP의 미확인 부분은 정책을 준수해 처리한다. 실행 불가이면 정확히 제한 사항으로 남긴다.
3. 변경 시 HTML 생성 → 검수 → 영수증/해시 갱신 → ZIP 재생성 순서를 지킨다.
4. Git 상태와 origin/main 차이를 확인하고 `codex/` 브랜치에서 필요한 커밋을 정리한다. `HANDOFF_JOB.md` 포함 여부도 사용자 의도에 맞춰 결정한다.
5. 기존 저장소 절차에 맞춰 PR·검사 후 main에 통합·푸시한다. 문서 변경이라도 Git 연동으로 웹 배포가 발생할 수 있으므로 해당 상태를 확인한다. API를 불필요하게 재배포하지 않는다.
6. 결과 보고에서 로컬 커밋/원격 푸시/main 통합/배포를 별개로 명시한다.

### 다음: 실제 공고에 맞춘 제출

- 구체적 채용 공고의 내용은 아직 확보하지 않았다. 최초 첨부 공고 이미지의 정확한 요구사항을 이 파일만으로 추정하지 않는다.
- 공고가 주어지면 이력서 3~4문장, 기술 선택 2~3개, 3분 설명을 맞춘다.
- LLM 서비스: 파일부터 저장·재접속까지의 제품 흐름, 실패 복구, 품질 관측.
- LLM orchestration: 도구 선택/Schema, 실행과 의미 성공의 구분, 지침 충돌 수정, 계약·정답 평가.
- AI 백엔드: 권한/출처 격리, SQL·Decimal 집계, 재계산 정의, 업로드 완료·재시도, 서버리스 상태.
- 멀티에이전트 분산 시스템, 파인튜닝, 모델 학습, 대규모 트래픽 운영 경험으로 확대하지 않는다.

### 선택 후속: 평가 고도화

- 프롬프트 수정에 쓰지 않은 새 파일/질문을 분리한 holdout을 설계한다. 기존 24문항을 unseen이라고 다시 명명하지 않는다.
- 독립 oracle, 모호함·범위·취소·기간·지원 불가 응답, 통과 기준을 평가 전에 고정한다.
- 실패한 질문을 자동 반복하거나 기대값을 모델 답변에 맞춰 고치지 않는다.
- 아직 이 작업은 착수하지 않았다. 제출 마감보다 먼저 임의로 확장하지 않는다.

## 9. 읽을 문서와 코드 위치

모든 아래 경로는 `D:\Github\DATAEZ` 기준이다.

| 목적 | 경로 |
|---|---|
| 현재 상태·과거 기록 구분 | `docs/CURRENT_STATUS.md`, `docs/DOCUMENTATION_AUDIT.md` |
| 문서 목차 | `docs/README.md` |
| 제품/계약 | `docs/PRD.md`, `docs/FILE_SCOPE_AND_FIRST_USE.md` |
| 배포/환경 | `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, `docs/DEPLOYMENT.md` |
| 포트폴리오 계획/사례 | `docs/PORTFOLIO_DEMO_PLAN.md`, `docs/portfolio-demo/CASE_STUDY.md` |
| QA/실행 | `docs/portfolio-demo/FINAL_QA.md`, `ACCEPTANCE.md`, `RUNBOOK.md`, `scenario.json` |
| LLM 실행/도구/지침 | `api/app/agent.py`, `router.py`, `library_agent.py`, `agent_tools.py`, `prompts.py` |
| 지표/범위/파일 | `api/app/metric_definitions.py`, `dashboard_metrics.py`, `file_snapshots.py`, `direct_uploads.py` |
| UI/배포 앱 | `web/app/`, `web/components/dashboard/`, `web/package.json` |
| 평가 구현 | `scripts/agent-quality/`, `samples/agent-quality-v1/`, `.github/workflows/agent-quality.yml` |

같은 표의 일부 축약 파일명은 바로 앞 전체 디렉터리 기준이다. 코드 주장에 사용할 때는 해당 파일·테스트를 실제로 읽는다.

## 10. 사용자 선호와 작업 원칙

- 한국어로 간결하고 구체적으로 보고한다. 사용자는 단계별 진행을 선호하지만 매번 불필요한 승인 질문으로 멈추는 것을 싫어한다.
- 사실관계를 매우 중시한다. 기능 존재, 실제 공개 검증, 모의 검사, 과거 기록, 남은 제한을 구분한다.
- 기여를 정직하게 설명한다. 사용자는 대상·범위·다중 가게·디자인·우선순위를 결정했고 Codex와 구현·검증·배포·자료 제작을 진행했다. 사용자 혼자 모든 코드를 작성했다고 쓰지 않는다.
- 실제 고객 수·사업 성과·비용 절감률·운영 SLA를 측정하지 않았다. 소개 자료에 임의 수치를 넣지 않는다.
- 비밀번호·JWT·서명 URL·DB 접속 문자열·실제 대화·개인 연락처를 공용 문서/코드/로그에 넣지 않는다. 이 파일에는 기존 관리자 이메일이나 합성 계정 식별자를 의도적으로 복사하지 않았다.
- 과거 QA JSON/촬영 파일을 덮어쓰지 않는다. 새 실행 ID와 별도 증거를 사용한다.
- 현재 환경에서 브라우저 UI 조작은 `mcp__cua_repl` 문서와 정책을 따른다. 과거 `*.cjs` UI 도구가 있다는 이유로 현재 도구 정책을 무시하지 않는다. 실행 환경/스킬 지침은 새 세션의 실제 지침을 우선한다.
- PDF를 만들면 PDF 스킬, Supabase를 직접 작업하면 Supabase 스킬, 구조도를 새로 만들면 Archify 등 해당 스킬을 읽는다. 단순 문서 인계/통합을 위해 불필요한 스킬·외부 서비스 작업을 늘리지 않는다.
- PowerShell/Python 출력은 UTF-8을 명시한다. `$env:PYTHONIOENCODING='utf-8'`, 파일 읽기/쓰기 `encoding='utf-8'`. 시스템 `$HOME` 등을 작업 변수로 재사용하지 않는다.
- 이 문서는 **인계 자료**다. 이전 `/goal`과 오래된 “다음 Phase” 요청을 새 작업으로 무한 재실행하지 않는다. 최신 사용자 요청과 현재 남은 작업을 기준으로 진행한다.
