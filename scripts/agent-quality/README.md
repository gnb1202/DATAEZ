# DATA:EZ 에이전트 품질 파이프라인

> 2026-09-14 후속: [PR #14](https://github.com/gnb1202/DATAEZ/pull/14)로 main 통합과 원격 CI 확인을 완료했다. 아래 09-13 미커밋·미푸시 설명은 당시 기록이다. [통합 검사 근거](../../docs/evaluations/integration-20260914/verification.json).

[실제 실행·발견 문제·수정 전후 결과](../../docs/AGENT_QUALITY_PIPELINE.md)

자연어 이해 → function calling → 지표 정의 → SQL 집계 → 차트 응답을 백엔드에서 검사한다. 질문은 `samples/agent-quality-v1/questions.json`에 있고, 실제 CSV/XLSX는 기존 `samples/unseen-v1`을 재사용한다. 24개 개발 회귀 문항이며, 기존 unseen holdout 10개를 새 평가의 비공개 시험처럼 주장하지 않는다.

## 실행

저장소 루트에서 실행한다. Python 3.12+, Node, Docker(실행 중), API 의존성, 웹의 ECharts 패키지가 필요하다.

```powershell
pip install -r api/requirements.txt -r api/requirements-dev.txt
npm ci --prefix web

# 네트워크·모델·DB 호출 없음: 질문과 기대값 검사 + 채점기 회귀
python scripts/agent-quality/run.py validate
python -m pytest scripts/agent-quality/test_quality.py -q

# 실제 라우터·분석 모델과 임베딩을 호출한다. 키는 환경변수 또는 .env에 설정.
python scripts/agent-quality/run.py live --suite smoke
python scripts/agent-quality/run.py live --suite full

# 부분 회귀. Q02는 이전 응답이 필요하므로 Q01부터 실행한다.
python scripts/agent-quality/run.py live --cases Q02,Q15

# 저장된 실제 응답 재채점: 모델 재호출 없음
python scripts/agent-quality/run.py report --run .local-test/agent-quality/<run-id>
python scripts/agent-quality/run.py report --run .local-test/agent-quality/<run-id> --reviews <reviews.json>

# 프롬프트/모델 변경 전후 비교. 같은 질문·선택 문항·fixture만 비교 허용.
python scripts/agent-quality/run.py live --suite smoke --compare <이전-assessment>/summary.json
```

모든 실행은 고유한 경로에 기록한다. 모델 질문의 자동 재시도는 0회이며, SDK 전송 재시도와는 별개다. 실제 실행은 유료 호출이다. 질문당 최대 8회 에이전트 루프, 24,000 소프트 토큰 예산, 200초 제한을 적용한다. 라우터·임베딩·내부 호출을 합친 정확한 청구 상한은 아니다. 전체 실행은 여러 분 걸릴 수 있다.

Docker 엔진이 없거나 키가 없으면 실제 평가를 시작하지 않고 명확히 중단한다. 공개 Supabase/운영 DB에 연결하는 대체 동작은 없다. 기존 `unseen-eval/run.py`의 임시 PostgreSQL·실제 HTTP·업로드·인덱싱·소유 리소스 정리를 재사용한다. DB 자료 생성과 임베딩 준비 비용도 발생한다. 원래 unseen 질문·manifest는 수정하지 않는다.

## 질문 구성

| 문항 | 확인 내용 |
|---|---|
| Q01–Q03 | 날짜별 선, 이전 답변을 받는 월별 막대, 결제수단·누락 그룹 |
| Q04–Q08 | 날짜 경계, 음수 취소, 중복 주문번호를 유지한 건수, 최댓값·최솟값 |
| Q09–Q10 | XLSX의 다른 컬럼명, NULL 수수료와 0 구분 |
| Q11–Q12 | 이후 거래가 반영된 누적 장부와 불변 원본의 차이 |
| Q13–Q16 | 필터와 날짜 그룹 조합, 0원 건수, 양수 원형 차트, 빈 기간 |
| Q17–Q18 | 구어체와 오타. Q01/Q18은 실제 SSE 경로 |
| Q19–Q24 | 순이익·수수료·고객 식별·환율 누락, 타 계정, 선택 범위 충돌 |

질문에 도구 이름이나 기대 금액을 주입하지 않는다. 현재 지원 계약을 확인하기 위해 대부분 재계산 미리보기와 저장 금지를 명시한다. 임의의 짧고 모호한 모든 질문에 대한 이해도를 측정한 것은 아니다. 후속 질문 Q02는 실제 같은 대화의 Q01 답변을 전달한다.

## 판정과 산출물

1. **Function calling:** 실제 tool trace의 도구명, 금지 쓰기 호출, JSON Schema 인자, preview 입력의 집계·그룹·필터를 확인한다. 라우터의 후보 도구 선택 점수는 기존 `python -m app.eval.run` L1 평가와 별개다.
2. **의미와 계산:** 소유·출처, 기간, 단위, 필터·그룹과 각 결과 셀을 독립 Decimal oracle과 비교한다. 답변에 정답 숫자가 포함됐다는 이유로 통과시키지 않는다.
3. **그래프 계약:** 정확히 1개, 재계산 정의, 유형, x/y 키, 날짜 정렬, 실제 셀과 출처를 확인한다. 중복 정적 차트나 막대/선 불일치도 실패다.
4. **엔진 렌더링:** 실제 응답을 ECharts SVG SSR로 렌더링해 SVG·비정상 좌표·데이터를 검사하고 이미지를 남긴다. React 대시보드·브라우저 상호작용·시각적 미감 검사는 아니며 기존 UI QA와 구분한다.
5. **거절·확인 응답:** 차트를 지어내지 않는지 자동 확인하되, 키워드만으로 설명의 타당성을 통과시키지 않는다. `review-template.json`에 원시 근거 해시·검토자·판정·이유를 채운다. 거짓 검토나 오래된 해시를 허용하지 않는다.

출력은 `.local-test/agent-quality/<run-id>/` 아래에 있다.

- `manifest.json`, `questions.json`: 실행 조건과 고정 질문 사본.
- `backend/case-Qxx.json`: 전체 실제 답변·도구 인자·결과·상태 전후. 로컬 전용.
- `assessment-*/report.html`: 문항별 통과/실패·차트·검사 항목.
- `assessment-*/summary.json`: 모델·소스·질문·grader 지문, 사용량, 기대/관측값, 변경 전후 비교.
- `assessment-*/review-template.json`: 설명 검토 양식. 실패한 자동 검사를 검토로 덮을 수 없다.
- `latest.json`: 가장 최근 재채점 경로. 최초 응답과 과거 판정은 덮어쓰지 않는다.

기본 종료 코드는 전체 계약과 필요한 설명 검토까지 통과하면 0, 판정 실패/검토 대기면 2, 실행 환경·도구 오류면 1이다. `--automatic-only`를 명시하면 자동 검사만으로 종료 코드를 정한다. 이 경우에도 보고서의 전체 `passed`는 검토 전 false이며 상태는 `needs_review`다. 워크플로 정의상 PR/push에서는 모델 호출 없는 검사, 명시적인 수동 실행에서만 실제 모델 호출을 수행한다. 2026-09-13 점검 시 워크플로는 아직 미커밋·미푸시 상태이며 원격 실행 성공을 확인한 것은 아니다. [현재 상태](../../docs/CURRENT_STATUS.md).

프롬프트를 바꾸면 실패 질문을 자동 반복해 좋은 결과만 고르지 말고 새 run으로 실행한다. 질문·기대값·채점 오류 수정과 제품 수정은 따로 기록한다. 토큰·비용은 저장소 가격표의 추정치이며 setup 임베딩과 질문 사용량을 구분한다.
