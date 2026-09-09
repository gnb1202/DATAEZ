# 2026-09-10 브랜치 통합 기록

누적 구현을 기능별 세 브랜치로 나누고 GitHub PR의 CI 통과를 확인한 뒤 순서대로 main에 머지했다. 그 후 main에서 README, 제품·개발 문서와 문서 목차를 갱신했다. 원격 서비스 배포 작업은 포함하지 않았다.

## 브랜치와 머지

| 브랜치 | 범위 | PR | main 머지 커밋 |
|---|---|---|---|
| `codex/data-platform` | 지표 v1–v5, 가져오기·현금·검색, 파일 원본 범위, DB 스키마와 API 테스트 | [#11](https://github.com/gnb1202/DATAEZ/pull/11) | `71a9f56` |
| `codex/analytics-workspace` | 확정 디자인, ECharts, 보관함·채팅·저장 설정·샘플 UI, 디자인 산출물 | [#12](https://github.com/gnb1202/DATAEZ/pull/12) | `cad24e7` |
| `codex/acceptance-suite` | 합성 CSV·엑셀, 독립 정답, DB·모델·브라우저 평가 도구, 공개 보고서 | [#13](https://github.com/gnb1202/DATAEZ/pull/13) | `87d4b1c` |

브랜치는 API → UI → 검증의 의존 순서로 만들었으며 merge commit 방식으로 통합했다. 원본 브랜치는 원격에 유지했다. 문서 수정은 위 세 머지 이후의 main 커밋으로 구분한다.

## 이번에 다시 확인한 내용

- 각 PR에서 **API Tests, Web Build, Build API Image, Build Web Image** 통과. CI는 실제 유료 LLM·외부 PostgreSQL 수용 시험을 실행하지 않는다.
- 마지막 PR #13의 Ubuntu CI API 검사는 **467 passed / 253 skipped**다. 아래 로컬 결과와 실행 환경·선택 의존성이 달라 통과·건너뜀 수가 다르다.
- 로컬 전체 API 검사: **481 passed / 239 skipped**. 외부 테스트 DB·선택 SQL 의존성을 설정하지 않은 환경이다.
- 오프라인 라우팅 골든셋: **65 cases / 32 known tools** 유효성 통과.
- 자연어 평가 도구의 정답·보고서 검사: **25 passed**.
- 합성 CSV **12개** 체크섬과 행 수, 엑셀 **533개 셀**의 값·타입 비교 통과.
- Git의 텍스트 줄바꿈 변환이 CSV 체크섬을 바꾸는 문제를 발견했다. 해당 샘플만 `.gitattributes`에서 원본 바이트를 유지하도록 지정했고, Git archive로 내보낸 파일도 체크섬이 일치함을 확인했다. 기존 셸·SQL·Dockerfile의 LF 규칙은 유지한다.
- 변경 파일의 자격 증명 패턴을 검사했으며 실제 키·토큰을 추가하지 않았다. `.env`와 원시 인증 세션·임시 실행 폴더는 계속 Git에서 제외한다.
- 문서 36개의 로컬 링크·앵커 228개, 코드 블록 구분과 문서 목차 연결을 검사했다. 문서 커밋에는 Markdown 파일만 포함한다.

## 앞선 구현에서 완료한 검증

이번 Git 정리에서 실제 LLM 시험을 다시 실행한 것은 아니다. 동일 구현의 완료 기록을 함께 보관했다.

| 검사 | 결과 | 근거 |
|---|---|---|
| 원본 범위·저장 설정·샘플 회귀 | 관련 API 222 passed / 67 skipped, UI fixture 32개 흐름 | [최신 구현 문서](FILE_SCOPE_AND_FIRST_USE.md) |
| 실제 작업 공간 통합 | 자연어 질문 6개·점검 29개 | [통합 검증](WORKSPACE_LIVE_ACCEPTANCE.md) |
| 자연어 50문항 전체 재평가 | 47/50, 이후 관련 회귀 10/10 | [자연어 평가](NATURAL_LANGUAGE_ACCEPTANCE.md) |

실제 통합 실행은 `dataez_workspace_live_8f227a173631429085f4004481598d42`다. 원본 **330,000.06원**과 거래 추가 후 누적 장부 **360,000.15원**, 샘플 가게 **690,200원**을 구분했다. 예정 시각을 앞당겨 실제 서버 스케줄러를 검사했으며 한 시간을 실제로 기다린 시험은 아니다.

## 문서 정리 범위

- [README](../README.md): 제품 흐름, 현재 기능, 실행, 검증과 미완료 범위.
- [문서 목차](README.md): 제품·개발·데이터·UI·검증·디자인 경로.
- [PRD](PRD.md): 확정된 다중 가게, 파일 보관함과 분석 범위, 저장 설정, 첫 사용 흐름.
- [아키텍처](ARCHITECTURE.md), [설정](CONFIGURATION.md), [실행·배포](DEPLOYMENT.md), [개발 안내](../CONTRIBUTING.md): 현재 코드와 일치하도록 갱신.
- [엔지니어링 기록](ENGINEERING_HISTORY.md): 이전 README의 측정·개선 기록을 보존하고 당시 수치임을 명시.

실제 사업자 사용성, 보지 않은 질문·파일 구조, 운영 부하와 원격 저장소 연결은 후속 검증이다. 실제 PG 파일과 외부 PG 연동은 사용자 결정에 따라 서비스 일정이 정해질 때까지 보류한다.
