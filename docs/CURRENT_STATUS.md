# DATA:EZ 현재 상태와 근거

갱신일: **2026-09-14**. 제품 기능, 공개 배포, 원격 소스, 검사 결과를 구분한다. 이 문서는 아래 확인 시점의 기록이며 실시간 상태판이 아니다.

## 09-14 제출 자료 마감 검증

제출용 한 페이지를 실제 320/390/1280px 브라우저 뷰포트에서 확인하고, 320px 툴바의 인쇄 버튼 줄바꿈을 보정했다. [A4 PDF](../output/pdf/DATAEZ-SUBMISSION.pdf)는 WeasyPrint 70.0으로 생성해 1장·한글·링크 3개와 전체 페이지 PNG를 검수했다. 제출 HTML/가이드의 고정·직무별·내장 구조도 링크와 제출 Markdown의 외부 링크 22개는 HTTP 200이었다.

이번 로컬 재검사는 API **545 passed / 268 skipped**, 웹 빌드 통과다. 실제 모델·공개 UI·DB 검사를 반복하지 않았다. ZIP 직접 열기는 이전 브라우저 URL 정책 차단을 존중해 미확인으로 유지한다. 인앱 PDF 내보내기도 지원되지 않아 브라우저 자체 인쇄 대화상자는 미검증이며, 동봉 PDF의 문서 렌더러 검수와 구분한다. [검증 범위와 재생성](portfolio-demo/SUBMISSION_QA.md) · [이번 실행 기록](evaluations/submission-20260914/verification.json).

## 2026-09-14 main 통합 완료

[PR #14](https://github.com/gnb1202/DATAEZ/pull/14)를 main에 머지했다. 통합 커밋은 `3524d22df4e3e419bd5cdc63190b84fdfecf352c`다. 품질 기능·색상 보정·문서/자료 세 커밋을 보존했다. 이번 문서 변경은 통합 뒤의 상태 기록이다.

로컬 API 545 passed / 268 skipped, 평가 도구 41 passed, 웹 빌드를 확인했다. 원격 PR 검사에서 API·웹·Docker 빌드와 Agent Quality offline/실제 PostgreSQL 관측(26 passed)이 통과했다. 유료 live 모델 job은 의도적으로 건너뛰었다. [원격 검사와 통합 근거](evaluations/integration-20260914/verification.json).

아래는 **09-13 점검 당시 배포/소스 기록**이다. 그때의 미통합·미푸시 상태는 이번 머지로 해소됐다. API는 이번 통합에서 별도 재배포하거나 운영 DB 마이그레이션을 재실행하지 않았다. 웹의 Git 연동 배포는 기존 수동 배포와 별도로 진행되므로 아래 09-13 배포 ID를 최신 자동 배포 ID로 해석하지 않는다.

## 09-14 통합 후 공개 확인

웹 소스 `ef934385e1c2126f85007bcf37f35489129cef16`에 연결된 Vercel 성공 상태를 확인하고, 별도 합성 계정으로 공개 UI의 샘플 시작 → 원본 선택 → 실제 질문 1회 → 집계표·SQL → 설정 검토·저장 → 재로그인·재계산을 확인했다. 일별 집계는 독립 Decimal 기대값과 일치했고 합계는 690,200원이다. 위젯 1개와 원본·전체 기간·KRW·수동 갱신 설정이 유지됐다.

이번에는 샘플 시작 버튼을 사용했다. 수동 CSV 업로드·계정 격리·모의 장애·24문항 평가·전체 Phase 5를 다시 수행하지 않았다. 합성 자료는 보존하고 검사 세션은 로그아웃했다. [별도 실행 기록](evaluations/post-merge-20260914/verification.json) · [독립 기대값](evaluations/post-merge-20260914/oracle.json).

[소개 HTML](portfolio-demo/PORTFOLIO_GUIDE.html)에 평가·관측·수동 회귀 후보 흐름을 추가하고 [제출용 한 페이지](portfolio-demo/SUBMISSION.html)와 [이력서 문장](portfolio-demo/SUBMISSION.md)을 구성했다. 과거 화면·영상은 새로 촬영하지 않았다.

## 09-13 배포와 소스 기록

| 대상 | 마지막 확인 상태 | 근거 |
|---|---|---|
| 공개 웹 | Vercel `dpl_6Cq7jr7f9GPCkS7cPAoMCk9HaLS1`, 색상 보정 반영 | [보정 검증](evaluations/color-polish/verification.json), [136개 파일 해시](evaluations/color-polish/web-manifest.json) |
| 공개 API | Vercel `dpl_3VyHSr7b5kB1aSCGRCfxTDr31d8T`, 품질 관측·지정 관리자 연결 | [배포 기록](evaluations/chat-quality-release/deployment.json), [96개 파일 해시](evaluations/chat-quality-release/api-manifest.json) |
| 공개 DB 스키마 | 품질 관측 마이그레이션 `20260913092842_dataez_chat_quality.sql` 적용 기록 | [마이그레이션](../supabase/migrations/20260913092842_dataez_chat_quality.sql), [적용·권한 검증](evaluations/chat-quality-release/deployment.json) |
| GitHub `main` | `148ab1bed5acbaf1b43ca18e022dba2e8f74e41e` | 09-13 `git ls-remote origin refs/heads/main` 조회 |
| 현재 로컬 | `codex/agent-quality-pipeline`, HEAD는 위 커밋이며 후속 작업은 미커밋 | [소스 대조](evaluations/documentation-audit/source-check.json) |

품질 평가 파이프라인, 대화 관측, 색상 보정, 관련 문서에는 미커밋·미추적 파일이 있다. 공개 배포는 이 작업 트리의 파일 사본을 사용했다. **배포 완료가 main 통합·원격 푸시 완료를 의미하지 않는다.** 신규 Agent Quality 워크플로도 아직 원격에 등록되지 않았고 원격 실행 성공을 확인하지 않았다.

문서 점검 시 API 96개·웹 136개 파일의 배포 manifest를 로컬 파일과 대조해 모두 일치했다. 이는 기록된 소스 파일의 일치이며 환경변수 전체·DB 데이터·빌드 의존성의 완전한 재현 검증은 아니다.

현재 공개 구성은 **Vercel 웹 + Vercel FastAPI + Supabase PostgreSQL/pgvector·비공개 Storage·Cron + OpenAI**다. 로그인은 FastAPI 자체 JWT다. AWS·Redis·Supabase Auth를 사용하는 배포로 설명하지 않는다. 코드의 기본 설정과 실제 배포 환경변수는 구분한다. [설정](CONFIGURATION.md) · [배포 안내](DEPLOYMENT.md)

## 09-13 문서 점검에서 직접 확인한 것

- 공개 웹 HTTP 200.
- API `/health` HTTP 200, `storage_backend=supabase`.
- API `/ready` HTTP 200, DB 연결 `ok`.
- 원격 main SHA와 현재 배포 manifest 대조.
- 문서의 주요 주장과 코드·기존 JSON 증거·로컬 링크 대조.

[HTTP 확인 시각·응답](evaluations/documentation-audit/http.json). 이번 문서 정리에서 회원가입·실제 모델 질문·전체 UI QA·DB 권한 검사·Cron 실행을 다시 수행하지 않았다. 건강 상태 응답만으로 이들이 정상이라고 판정하지 않는다. 기존 사용자 대화나 매출은 조회하지 않았다.

## 검증 결과를 설명하는 기준

| 시점·대상 | 확인한 결과 | 해석 범위 |
|---|---|---|
| 09-12 포트폴리오 Phase 5 | 합의한 필수 검사 통과, 해당 범위 미해결 P0/P1 없음 | [당시 버전·실제/모의 구분](portfolio-demo/FINAL_QA.md). 이후 변경 전체의 재검증은 아님 |
| 09-13 개발 회귀 24문항 | 수정 전 22/24 → 수정 후 24/24 | [도구·정의·Decimal 집계·차트](AGENT_QUALITY_PIPELINE.md). 설명 6문항은 Codex 검토, 일반 정확도나 독립 사람 평가가 아님 |
| 09-13 품질 관측 회귀 | 전체 API 545 passed / 268 skipped 기록; 별도 관측 26개에 실제 PostgreSQL 8개 포함 | [기존 실행 기록](CHAT_QUALITY_OBSERVABILITY.md#검증). 겹치는 검사 수를 더하거나 skip을 통과로 계산하지 않음 |
| 09-13 공개 품질 기능 | 실제 질문 1회, 실행·메시지·사용량 연결, 평가 재시도, 계정 격리 | [공개 검증](evaluations/chat-quality-release/deployment.json). 24문항 공개 재평가는 아님 |
| 09-13 관리자 연결 | 지정 계정의 실제 API 접근·검토 저장과 일반 계정 차단 | [검증](evaluations/chat-quality-release/admin-verification.json). 단기 서버 서명 토큰 사용; 관리자 브라우저 로그인 자동화는 아님 |
| 09-13 색상 보정 | 실제 컴포넌트 다크/라이트 + 공개 로그인, 빌드·lint 오류 없음 | [검증](evaluations/color-polish/verification.json). 합성 fixture 검사이며 전체 인증 UI 재검사는 아님 |

## 후속 작업과 한계

- 완료 (09-14): 변경을 세 커밋으로 정리해 PR #14에서 main·원격에 통합했다.
- 완료 (09-14): 신규 GitHub Actions의 offline/관측 검사를 확인했다. 유료 평가용 secret·실제 live job 검증은 별도 후속이다.
- 전체 최종 QA를 새 배포에서 다시 요구할 경우 새 실행 ID로 수행하기. 과거 증거 덮어쓰기 금지.
- 영상 마스터·전달 ZIP은 로컬 산출물이고 공개 영상 URL은 없다. 초기 HTML·과거 캡처·영상은 최신 앱 색상과 자동 동기화되지 않는다.
- 실제 PG 연결, 고객 사용성 관찰, 대규모 부하, 전문 보안 감사는 미수행 후속 과제다.
- 대화 실행 기록은 적용 후부터이며 `completed`는 정답 판정이 아니다. 관측 쓰기 실패·종료 시 사용량 누락 가능성과 90일 TTL의 실행 조건은 [관측 한계](CHAT_QUALITY_OBSERVABILITY.md)를 따른다.
