# DATA:EZ 대화 품질 관측

사용자 질문 → 실행 기록 → 사용자 평가 → 관리자 검토 → 합성 회귀 질문 → 백엔드 평가를 연결한다.
2026-09-13 공개 Supabase 스키마와 Vercel API·웹에 적용했다. 실제 공개 환경 검증과 지정된 관리자 계정의 가입 확인·권한 연결을 완료했다. [배포 증거](evaluations/chat-quality-release/deployment.json)를 참조한다.

## 저장하는 정보

| 자료 | 저장 위치·범위 |
|---|---|
| 질문, 최종 답변, 선택 파일/범위, 도구 입력·출력, 차트, 집계표 | 기존 `messages`. 긴 도구 출력은 기존 3,000자 제한을 유지 |
| 실행 ID, 대화 ID, 질문/답변 메시지 ID, 시작·종료·소요 시간 | `quality_runs`. 대화의 `user_id`로 사용자·가게 연결 |
| 모델·버전 | 실행 당시 worker/router 설정, 관련 5개 코드 파일의 SHA-256, 릴리스, 반복·토큰 제한 |
| 호출별 사용량 | `messages.usage.call_details`: 모델, 역할, 입력/출력 토큰, 시간, 성공/오류, 추정 비용 |
| 사용자 평가 | `message_feedback`: 답변당 좋아요/아쉬워요 1개, 문제 분류, 선택 의견. PUT 재전송은 갱신 |
| 관리자 판정 | 실행에 최신 판정·분류·근거·검토자·시각. 상세 열람/검토/내보내기는 기존 audit_log 기록 |
| 합성 후보 | 실패로 검토한 실행에 관리자가 새로 작성한 질문·기대 동작·합성 확인 |

버전 해시는 `prompts.py`, `library_agent.py`, `router.py`, `agent.py`, `agent_tools.py`의 이름과 내용으로 계산한다. 전체 모델 입력 프롬프트, API 키, 인증 헤더를 별도 기록하지 않는다. 모든 종속 코드와 데이터의 완전한 재현 스냅샷을 뜻하지 않는다. 비용은 저장된 가격표에 의한 추정이며 청구 금액이 아니다.

## 실행 상태의 의미

- `running`: 관측을 시작했다. 인증과 대화 소유권 검사를 통과한 요청에만 생성한다.
- `completed`: 동기 결과 또는 스트리밍 done을 확인했다. **정답·품질 통과 판정이 아니다.**
- `failed`: 요청 처리 예외, HTTP 오류, agent error 또는 스트리밍 오류를 확인했다.
- `cancelled`: 취소되었거나 완료 이벤트 없이 스트림이 끝났다. 부수효과가 없었다는 의미는 아니다.
- `unconfirmed`: 10분 이상 running인 실행을 조회 시 이렇게 표시한다. 프로세스 강제 종료도 성공으로 추정하지 않는다.

토큰 한도·반복 한도·키 미설정·모델 오류·출력 미완료는 `usage.turn_outcome`으로 구분한다. 사용자에게 안내 답변이 반환되더라도 관리자 실행 상태는 failed이다. 스트리밍 모델 오류에서는 error 프레임 전에 확보한 사용량을 meta로 전달해 저장한다.

인증·소유권·FastAPI 입력 검증에서 거부된 요청은 대화 실행으로 기록하지 않는다. 에이전트 실행 전 예산/파일 검증 등에서 실패하면 메시지 연결이 비어 있을 수 있다. 종료 전에 확보하지 못한 호출 사용량은 복구되지 않을 수 있다. 관측 DB 쓰기가 실패하면 `quality_observation_write_failed`를 서버 로그에 남기며 분석이나 거래를 재실행하지 않는다. 이것은 완전한 감사 시스템이나 exactly-once 분석 실행 기능이 아니다.

## 관리자 사용법

1. 실제 운영자의 자체 인증 `users.id`를 확인해 API 환경 변수 `QUALITY_ADMIN_USER_IDS`에 지정한다. 여러 명이면 쉼표로 구분한다. 기본값은 빈 목록이다. 이메일·회원가입 입력·클라이언트 값으로 권한을 부여하지 않는다.
2. `QUALITY_RELEASE`에는 API 릴리스 식별자를 지정한다.
3. 기존 배포 절차의 `initialize_database()`를 실행한다. 끝에서 `ensure_quality()`가 두 테이블·인덱스·RLS를 반복 실행 가능한 방식으로 준비한다. 배포에서는 스키마 준비 후 API와 웹을 반영한다. 이번 배포에서는 기존 정리 작업 실행을 피하기 위해 `supabase/migrations/20260913092842_dataez_chat_quality.sql`만 적용하고 migration history에 기록했다.
4. 관리자 계정으로 로그인하면 **설정 및 계정 → 대화 품질 검토**에서 `/quality`를 연다.
5. 실행 실패·중단·미확인·부정 평가·미검토를 필터링한다. 사용자 UUID로도 조회할 수 있다. 30건 단위로 페이지를 이동한다.
6. 질문·답변, 선택 자료, 도구 호출/SQL, 차트·집계표, 호출 사용량을 보고 판정과 근거를 저장한다.
7. 실패 판정인 경우 원본과 구분되는 합성 질문과 기대 동작을 작성하고 확인 후 저장·JSON 내보내기한다.

사용자는 본인 소유의 assistant 메시지만 평가할 수 있다. 사용자 ID는 요청 본문에서 받지 않는다. GET 응답은 no-store이며 관리자 여부도 서버에서 검증한다. Supabase의 anon/authenticated/PUBLIC 역할에는 새 테이블 권한을 주지 않고 RLS를 활성화한다. 자체 JWT 백엔드의 DB 연결은 기존처럼 테이블 소유자/권한 있는 서버 역할로 실행한다. 권한 근거: [Supabase Data API 보안 문서](https://supabase.com/docs/guides/api/securing-your-api).

## 회귀 테스트에 편입

내보내기에는 원본 질문/답변, 사용자 ID, 실행 ID, 파일/행/도구 출력이 포함되지 않는다. 합성 여부는 관리자의 확인이며 자동 개인정보 검출을 통과했다는 뜻이 아니다. 별도의 실제 매출 자료를 업로드하거나 원본 대화를 공개 저장소에 추가하지 않는다.

후보 JSON만으로 정답 데이터가 생기지는 않는다. 기존 합성 fixture에 맞춰 테스트 계약을 작성한다. 기존 질문 사례를 참고해 `id`, `question`, `file`, `scope`, `mode`, 필요 도구·차트·집계 정의와 `expected`를 정하고, `review`에는 후보의 `expected_behavior`를 그대로 넣는다. `question`도 후보와 정확히 일치해야 한다. 기존 fixture로 재현할 수 없으면 합성 fixture와 독립 정답 계산기를 먼저 확장한다.

```powershell
# 프로젝트 루트. 후보와 계약은 수동 검토 후 준비한다.
python scripts/agent-quality/promote.py --candidate .local-test/regression-candidate.json --contract .local-test/regression-contract.json --output .local-test/questions-next.json
python scripts/agent-quality/run.py validate --questions .local-test/questions-next.json
# 아래 명령만 실제 모델 호출 비용이 발생한다. 새 질문을 명시적으로 선택한다.
python scripts/agent-quality/run.py live --questions .local-test/questions-next.json --cases Regression01
```

편입 명령은 기존 질문셋을 덮어쓰지 않고 새 파일을 생성한다. 중복 ID, 질문/검토 기준 불일치, 비합성 후보, 원본 필드 포함, Decimal 정답 불일치를 거부한다. 실행과 정성 검토까지 통과한 후 새 버전의 질문셋으로 관리한다. [기존 평가 파이프라인](AGENT_QUALITY_PIPELINE.md)을 참조한다.

## 보관·삭제와 한계

- 질문/답변을 별도 관측 테이블에 복제하지 않는다. 대화 삭제 시 실행·평가·후보도 FK CASCADE로 함께 삭제한다. 내보낸 로컬 후보 파일은 별도 보관 대상이다.
- 기존 `CONVERSATION_TTL_DAYS=90`은 마지막 대화 갱신 기준이다. 초기화 시 정리하는 기존 동작을 유지하며, 서버리스에서 정확히 매일 삭제된다고 보장하지 않는다. 이번 작업에서 기존 대화를 삭제하거나 새로운 정기 삭제 작업을 실행하지 않았다.
- 적용 전 대화에 실행 기록을 소급 생성하지 않는다. 기존 메시지에 평가는 남길 수 있지만 해당 대화의 과거 실행은 새 관리자 실행 목록에 나타나지 않는다.
- 관리자 판정은 최신 값으로 갱신한다. audit_log는 누가 검토했는지 기록하지만 과거 판정 내용 전체를 버전별로 보관하지 않는다.
- 승인된 합성 후보를 자동 배포/학습에 사용하지 않는다. 이 화면은 평가와 테스트 후보 수집 기능이며 모델 학습 기능이 아니다.
- 공개 스키마·API·웹 배포와 실제 질문/평가/격리 검증은 완료했다. 지정된 계정의 관리자 권한을 연결하고 공개 API에서 조회·검토 저장 및 일반 계정 차단을 확인했다. 관리자 브라우저 로그인은 자동화하지 않았으며 로그인 후 `/quality`에서 사용할 수 있다.

## 검증

2026-09-13 로컬 검증. 실제 사용자·공개 DB와 분리했다.

- 신규 lifecycle/API/실제 PostgreSQL 검사 **26개 통과**: 동기·SSE 메시지 연결, 오류·취소·미완료, 한도 종료 판정, ContextVar 정리, 권한, 동일 평가 재전송, RLS/공개 권한, 대화 삭제 시 연쇄 삭제, 합성 후보 내보내기.
- 평가 파이프라인 단위 검사 **41개 통과**: 기존 35개 + 후보 편입 6개.
- 전체 API 검사 **545개 통과 / 268개 DB 등 선택 검사 건너뜀**. 위 PostgreSQL 8개는 별도 실행한 것이며 전체 실행의 skip을 통과로 계산하지 않는다.
- 실제 Next.js + Edge, API 응답은 격리된 모의 응답: 관리자 검토 → 합성 후보 다운로드, 비관리자 화면 차단, 답변 평가 응답 유실 → 초안 유지 → 재시도 → 새로고침 후 평가 복원.
- Edge 데스크톱 1440×900 / 태블릿 768×1024 / 모바일 에뮬레이션 390×844, 다크·라이트 가로 넘침 검사. 실제 iPhone/Safari 검사가 아니다.
- UI 증거: `.local-test/quality-observability/ui/receipt.json` 및 같은 폴더의 PNG. 테스트: `node scripts/ui-eval/quality.cjs` (`UI_BASE_URL` 기본 `http://127.0.0.1:3140`).
- 변경한 웹 파일의 ESLint와 Next.js 프로덕션 빌드 통과. 빌드는 API URL 미설정 경고가 있는 로컬 검사이며 실제 배포가 아니다.
- GitHub Actions `Agent Quality`에 실제 PostgreSQL 관측 검사와 후보 편입 단위 검사를 추가했다. 원격 실행·실제 모델 재평가는 이번 변경에서 하지 않았다.

```powershell
python -m pytest api/tests -q
# DATAEZ_TEST_DATABASE_URL은 반드시 전용 테스트 DB를 지정한다.
python -m pytest api/tests/test_quality.py api/tests/test_quality_postgres.py -q
python -m pytest scripts/agent-quality -q
npm run build --prefix web
```

## 공개 배포 검증 (2026-09-13)

- 공개 API + Supabase + 실제 모델 질문 1회. 합성 CSV의 일별 KRW 선그래프 30,000원/40,000원과 도구 호출, 실행·질문·답변 연결 및 사용량을 확인했다.
- 평가 PUT 재전송 시 1개 유지, 다른 계정의 평가 조회/수정 차단, 비관리자 실행 목록 차단, 잘못된 입력을 failed로 기록, 해당 합성 대화 삭제 시 관측 기록의 연쇄 삭제를 확인했다.
- 배포 검증용 합성 계정과 성공 실행 1개는 관리자 검토 예시로 보존했다. 비밀번호·토큰은 Git에서 제외된 로컬 경로에만 보관하며 공개 증거에 포함하지 않았다.
- 관리자 등록은 사용자가 지정한 이메일의 회원가입 확인 후 UUID를 환경 변수에 연결하는 방식이다. 다른 계정을 임의로 관리자로 승격하지 않았다.
- 실제 공개 웹의 Edge 검사에서도 저장된 평가 복원과 비관리자 검토 화면 차단을 확인했다(API 모의 응답 없음).

## 관리자 연결 완료 (2026-09-13)

지정된 등록 계정의 UUID만 운영 API의 `QUALITY_ADMIN_USER_IDS`에 등록하고 API를 재배포했다. 실제 운영 API에서 관리자 확인, 합성 실행 목록·상세·사용량 조회, 검토 저장 및 재조회, 일반 계정의 목록·상세·검토 수정 403, 비인증 차단을 확인했다. 검증에는 5분 유효 서버 서명 access token을 메모리에서만 사용했으며 비밀번호 변경이나 새 refresh token 생성은 하지 않았다. 기존 사용자 매출 자료는 조회·변경하지 않았다. [관리자 연결 검증](evaluations/chat-quality-release/admin-verification.json).
