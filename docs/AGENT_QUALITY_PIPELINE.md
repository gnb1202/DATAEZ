# 자연어·도구 호출·그래프 품질 파이프라인

2026-09-13 · 로컬 격리 환경의 실제 모델 평가

[실행 방법](../scripts/agent-quality/README.md) · [24문항과 기대값](../samples/agent-quality-v1/questions.json) · [수정 후 HTML](evaluations/agent-quality-v1/after/report.html) · [최초 설명 검토 결과](evaluations/agent-quality-v1/baseline/report.html)

## 실행 방법

저장소 루트에서 실행한다. `.env` 또는 환경변수의 모델 키와 실행 중인 Docker가 필요하다. 공개 서비스 DB를 사용하지 않는다.

```powershell
# 무료·오프라인: 질문, 독립 정답, 채점기 확인
python scripts/agent-quality/run.py validate
python -m pytest scripts/agent-quality/test_quality.py -q

# 실제 모델·임베딩 호출: 빠른 6문항 / 전체 24문항
python scripts/agent-quality/run.py live --suite smoke
python scripts/agent-quality/run.py live --suite full

# Q02는 Q01의 실제 답변을 포함한 후속 질문
python scripts/agent-quality/run.py live --cases Q02,Q15
```

결과는 `.local-test/agent-quality/<run-id>/assessment-*/report.html`과 `summary.json`에 남는다. 기본 명령은 설명 검토가 필요한 문항을 `needs_review`로 남기고 종료 코드 2를 반환한다. `review-template.json`에 실제 근거를 검토한 결과를 작성한 뒤 `report --run ... --reviews ...`로 재채점한다. 모델을 다시 호출하지 않는다. CI에서 자동 계약만 확인하려면 `--automatic-only`를 명시한다.

## 실제 확인 결과

모델은 두 실행 모두 worker `gpt-5.4`, router `gpt-5.4-nano`이며 같은 질문·CSV/XLSX·기대값을 사용했다. 모델 질문은 실행당 24개, 총 48개다. 같은 문항의 자동 재질문은 없었고 프롬프트 수정 후 새 실행을 명시적으로 시작했다.

| 확인 항목 | 프롬프트 수정 전 | 수정 후 |
|---|---:|---:|
| Function calling 계약 | 24/24 | 24/24 |
| 지표 의미·계산 조건 | 18/18 | 18/18 |
| 정확한 집계 셀·SQL | 18/18 | 18/18 |
| 차트 개수·종류·축·정의·값 | 9/9 | 9/9 |
| ECharts SVG 렌더링 | 9/9 | 9/9 |
| 정보 부족·권한·범위 설명 검토 | 4/6 | 6/6 |
| 최종 문항 판정 | 22/24 | **24/24** |

행들은 겹치는 검사 범위이므로 합산하지 않는다. 9개 차트 중 빈 기간 문항은 빈 데이터 상태를 확인한 것이며 실제 선이 생겼다는 뜻이 아니다. 설명 6개는 Codex가 실제 답변·도구 근거·서비스 계약을 대조한 검토이고, 독립 사람 평가나 LLM judge의 블라인드 점수가 아니다. 나머지 수치 문항의 모든 문장·인사이트를 자동으로 검증한 것은 아니다.

이 평가 시점의 검사 도구 회귀는 **35 passed**, API 전체 회귀는 **525 passed / 260 skipped**였다. DB 의존 등 건너뛴 260개를 실행한 것으로 계산하지 않는다. 별도의 실제 임시 PostgreSQL 평가와 혼동하지 않는다.

## 실제로 찾은 두 프롬프트 문제

- **Q22:** 모델이 환율 기준일을 알려주면 환산을 진행할 수 있는 것처럼 안내했다. 현재 외부 환율 조회와 통화 환산 재계산 지표를 지원하지 않는다는 한계를 범위 프롬프트에 명시했다. 새 실행은 원화만의 조회값을 구분해 제시하고 USD는 합산하지 않았으며, 준비된 원화 환산 자료나 통화별 분리를 안내했다.
- **Q24:** 원본 선택을 유지하면서 같은 파일의 누적 범위를 추가 선택하라고 안내했다. 실제 `resolve_references`는 한 파일에 한 범위만 허용한다. 해당 파일의 분석 범위를 변경하고 원본/누적 비교는 별도 분석으로 수행하도록 명시했다. 새 답변은 실제 UI 동선과 일치했다.

수정은 [library_agent.py](../api/app/library_agent.py)의 범위 안내 두 문단이다. 데이터 집계·권한 코드나 사용자 파일을 수정하지 않았다. 24문항 결과는 로컬 코드와 임시 평가 API에 대한 것이다. 이 평가 당시에는 공개 API를 재배포하지 않았지만, 이후 [대화 품질 관측 배포](evaluations/chat-quality-release/deployment.json)에 해당 프롬프트 수정이 포함됐다. 공개 환경에서는 별도 합성 질문 1회를 확인했으며, 24문항을 공개 서버에서 재실행했다는 뜻은 아니다.

## 채점기 보정도 기록했다

첫 grader v1은 `2026-09-01`과 `2026-09-01 00:00:00`을 다른 필터로 보아 자동 22/24였다. v2는 날짜 컬럼의 동일 자정 표현만 정규화했다. 수정 후 모델 실행에서는 명시적 `+09:00` 표현이 나타나 v2 자동 23/24가 됐다.

별도 임시 PostgreSQL에서 `timestamp`와 `timestamptz`, 한국 시간, 월 경계 직전의 마이크로초 자료로 동등성을 확인했다. v3는 해당 날짜 컬럼의 한국 시간 자정 표현을 함께 인정한다. 다른 시간·다른 오프셋·비교 연산자·일반 텍스트 값은 그대로 구분한다. 계산값·질문·기대값은 바꾸지 않았고 저장된 실제 응답만 재채점했다.

[첫 grader v1 원본 결과](evaluations/agent-quality-v1/first-grader-v1.json) · [독립 날짜 경계 실험](evaluations/agent-quality-v1/date-boundary-control.json) · [최종 비교 JSON](evaluations/agent-quality-v1/after/summary.json)

## 파이프라인의 경계

- 실제 HTTP의 동기·SSE 메시지 경로, 파일 원본·누적 범위, 임시 DB와 실제 임베딩·모델을 사용한다. fixture는 기존 unseen-v1의 독립 Decimal oracle을 재사용한다.
- 현재 문항은 개발 회귀용이며 프롬프트 보완에 사용했다. 처음 보는 질문에 대한 100% 정확도나 운영 성능으로 해석하지 않는다. 기존 unseen holdout은 이번에 실행하지 않았다.
- 그래프 이미지는 실제 백엔드 응답을 ECharts 엔진으로 렌더링한 결과다. React 대시보드의 상호작용·반응형·미적 완성도는 별도 UI 검사다.
- 생성된 HTML·SVG를 브라우저에서 확인했고 비정상 실행 오류·가로 넘침을 검사했다. 실제 대시보드 24문항 UI 테스트로 표현하지 않는다.
- 각 실행은 질문 사본, 소스·프롬프트·도구 스키마·grader 해시, 사용량과 이전 판정을 보존한다. 보고서의 비용은 저장소 가격표 추정치로 실제 청구액이 아니다.
- `.github/workflows/agent-quality.yml`에 PR/main 변경 시 오프라인·실제 PostgreSQL 검사, 수동 실행에서만 유료 평가를 하도록 정의했다. 09-13 문서 점검 시 이 파일은 아직 미커밋·미푸시 상태이고 원격 Actions 실행·시크릿 등록은 확인하지 않았다. 공개 앱 배포 여부는 [현재 상태](CURRENT_STATUS.md)에서 별도로 관리한다.

Docker Desktop 기동 시 접근할 수 없는 과거 Unix socket 항목이 있어 해당 런타임 폴더를 로컬 백업으로 보존하고 새로 생성하게 했다. 이미지·볼륨·운영 DB 초기화는 하지 않았다. 각 평가의 임시 컨테이너와 API는 종료·정리 완료를 확인했다.

## 운영 대화에서 회귀 질문으로

[대화 품질 관측](CHAT_QUALITY_OBSERVABILITY.md)의 관리자 검토에서 합성 후보를 내보낸 뒤 `scripts/agent-quality/promote.py`로 독립 정답이 있는 테스트 계약을 검증해 새 질문셋에 편입할 수 있다. 원본 대화나 실제 매출 자료를 질문셋에 자동 복사하지 않는다.
