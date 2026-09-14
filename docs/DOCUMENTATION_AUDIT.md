# DATA:EZ 문서 사실관계 점검

2026-09-13 · README와 현재 운영/개발 안내를 대상으로 한 1차 정리. [현재 상태](CURRENT_STATUS.md)를 상태 설명의 시작점으로 삼는다.

## 바로잡은 내용

| 발견 내용 | 수정·근거 |
|---|---|
| 배포 안내에 API 공개 대기·인증 비활성 설명이 남음 | 현재 웹/API 연결과 Supabase 구성으로 수정. [실제 HTTP 확인](evaluations/documentation-audit/http.json) 및 기존 배포 기록 대조 |
| 공개 배포와 main 소스가 같은 것처럼 읽힘 | 원격 main `148ab1b`와 작업 트리 배포를 분리. [현재 소스 대조](evaluations/documentation-audit/source-check.json) |
| 요청 제한이 메모리 전용으로 설명됨 | `rate_limiter.py`에 따라 persistent 메모리 / serverless PostgreSQL 시간창 구분 |
| 환경변수 표에 프로필별 기본값·품질 관리자 설정 누락 | `config.py`와 비교해 pool/worker/agent 제한, `QUALITY_ADMIN_USER_IDS`, `QUALITY_RELEASE` 정리 |
| 마이그레이션이 항상 시작 시 실행되는 것처럼 설명됨 | serverless 초기화 비활성 및 별도 스키마 적용 절차 명시. initializer의 만료 대화 삭제도 함께 설명 |
| 대화 90일 TTL이 정기 삭제 보장으로 오해될 수 있음 | 마지막 갱신일 기준과 초기화 시 실행을 구분. 서버리스 일일 정리 보장은 없음 |
| 품질 파이프라인의 로컬 결과·원격 CI·공개 배포 경계가 불명확 | 로컬 24문항, 공개 질문 1회, 미푸시 workflow와 원격 실행 미확인을 분리 |
| 품질 평가 문서에 “공개 API 재배포하지 않음”만 남음 | 평가 당시 사실은 유지하고 이후 관측 배포에 프롬프트 수정이 포함됐음을 연결 |
| README/구조 문서에서 대화 품질 관측 누락 | 기록·사용자 평가·지정 관리자·수동 합성 후보·재평가 흐름 및 보관 한계 연결 |
| 팔레트 문서에 앱 통합 예정·Recharts·옛 색상·잘못된 muted 토큰 | 실제 앱 `theme.css` 기준, 현재 ECharts, 09-13 보정값으로 정리. 초기 시안 대비 수치는 당시 값으로 보존. 데이터 색상이 결제수단에 자동 고정 매핑된다는 설명도 바로잡음 |
| 예전 최종 QA를 최신 변경 전체의 통과로 읽을 수 있음 | README·FINAL_QA·ACCEPTANCE·사례·제작 계획에 날짜/버전과 후속 검사 경계 추가 |
| 개발 안내에 신규 평가/관측 검사 실행법 누락 | 실행 명령·전용 DB·모의 UI와 실제 모델의 구분 추가 |

## 검증 방법

- API 배포 manifest 96개 파일과 웹 manifest 136개 파일을 로컬 SHA-256과 대조했다. 불일치·누락 없음. manifest에 없는 환경변수·DB 데이터까지 비교한 것은 아니다.
- 공개 웹과 API health/ready를 읽기 전용 HTTP로 확인했다. 사용자 계정이나 모델 호출 없이 수행했다.
- 주요 설정명은 `api/app/config.py`, 실행 프로필은 `runtime_defaults`/`validate_runtime`, 저장·조회는 `quality.py`, 관측 초기화·TTL은 `main.py`/`db.py`와 대조했다.
- 24문항 수정 후 JSON의 `total=24`, `passed=true`를 확인하고, 정성 검토 6개와 수치/차트 계약을 구분한 기존 보고서를 유지했다.
- 18개 문서의 Markdown 상대 링크 313개에 대해 파일/폴더 존재를 검사해 누락 0개를 확인했다. [검사 범위·결과](evaluations/documentation-audit/links.json). 외부 링크 전체와 URL fragment는 전수 검사하지 않았다.
- Supabase의 [Data API 보안 설명](https://supabase.com/docs/guides/api/securing-your-api)에서 grants와 RLS의 역할을 확인했다. 이번에는 DB/권한 설정을 변경하거나 보안 검사를 다시 실행하지 않았다.

## 보존한 기록과 범위 밖 항목

과거 Phase JSON, 영상·자막·스크린샷과 당시 검사 수는 바꾸지 않았다. API 545 passed / 268 skipped 등 기존 시험 결과를 이 문서 작업에서 새로 실행한 결과로 보고하지 않는다. 앱 코드·배포·DB에는 변경을 가하지 않았다.

포트폴리오 HTML·초기 시안·영상은 이전 근거로 만든 산출물이며 이번 정리에서 재생성하지 않았다. 최신 대화 품질 기능을 포함한 새 소개 자료가 필요하면 원본 템플릿부터 갱신하고 렌더링을 별도 확인해야 한다. 모든 과거 Phase 문서의 문장, 외부 링크, 공개 자료의 비밀정보를 전수 감사한 결과도 아니다.

남은 운영 작업은 소스 커밋/main 통합/원격 푸시, 신규 Actions 확인이다. 테스트 수치 갱신만으로 이 작업들이 완료됐다고 표시하지 않는다. [상태와 후속 항목](CURRENT_STATUS.md#후속-작업과-한계).
