# DATAEZ 의사결정 라우터 첫 개발 실험

2026-10-03 KST에 Laya multilingual의 12개 개발 라우팅 사례를 실제 실행했다. 현재의 전체 라우팅 정책을 state에 넣고 intent Choice 하나와 도구별 Noul 32개를 묻는 **첫 이식 방식은 보류**한다. 모델이 호출된 열 사례 모두 32개 도구를 선택했고 금지 도구 선택 검사를 실패했다. 이는 이 모델·질문 표현·threshold 조합의 개발 결과이며, Laya 전체의 성능이나 최종 서비스 도입 우위를 확정하는 결과가 아니다.

[평가 설계](DECISION_MODEL_EVALUATION_PLAN.md), [실행 방법](../scripts/decision-eval/README.md), [합성 사례](../samples/decision-routing-v1/pilot.yaml), [재집계](evaluations/decision-routing-20261003/laya-scorecard.json), [원시 관측](evaluations/decision-routing-20261003/laya-observations.jsonl), [실행 manifest](evaluations/decision-routing-20261003/laya-manifest.json)를 함께 보관했다. 비밀키와 실제 고객 자료는 포함하지 않는다.

## 실행 범위와 결과

| 비교군 | 실행 상태 | 결과 해석 |
|---|---|---|
| A0 현재 gpt-5.4-nano | 첫 API 호출부터 `credit_balance_exhausted`; 3사례에서 degraded 읽기 도구 집합 반환 후 중단 | 정상 모델 응답 없음. 새 기준 성능은 N/A. 폴백으로 문항 하나가 통과한 것을 nano 성능으로 세지 않음 |
| A1 원자 질문 nano | 1사례에서 RateLimitError 후 중단 | N/A. 기존 과거 성능을 이 비교의 점수로 대체하지 않음 |
| B0 Laya multilingual | 별도 12사례 완료, 전송/추론 오류와 degraded 모두 0 | 아래 개발 결과만 보고 |
| C0 Jev 1.13.0 | adapter·HTTP 계약 테스트 완료, 로컬 키 없어 실제 호출 미실행 | N/A. 실제 API 동작과 품질은 아직 검증하지 않음 |

A0/A1과 최초 B0 한 건의 중단된 기록은 [별도 집계](evaluations/decision-routing-20261003/interrupted-scorecard.json)로 남긴다. 완료된 B0의 점수에 더하지 않는다.

| 완료된 B0 지표 | 측정값 |
|---|---:|
| 계획 / 실행 | 12 / 12 |
| 전체 조건 통과 | 2 / 12, 16.7% |
| 모델 판단이 있는 사례 통과 | 0 / 10 |
| shortcut 통과 | 인사·첨부 2 / 2 |
| intent accuracy, shortcut 포함 | 33.3% |
| 평균 문항별 도구 F1, shortcut 포함 | 0.265 |
| 금지 도구 선택 사례 | 10 / 12 |
| 전체 라우팅 p50 / p95 | 75.08초 / 82.81초 |
| 모델 판단 케이스만의 p50 | 78.49초 |
| 전기·호스팅 비용 | 미측정, null |

worker·SQL·DB 반영은 실행하지 않았다. 금지 도구 **선택**을 실제 삭제나 쓰기 실행으로 표현하지 않는다. 이 12사례는 사람 승인 전의 Codex 검토 development 자료이며 holdout이 아니다. 설계 문서의 36개 전체 업무 episode를 완료한 것도 아니다.

## 모델과 입력

Laya SDK는 `0.3.24`, 공개 모델은 `convaiinnovations/laya-multilingual`의 revision `e4e9ddf21a7b1903b7acffd8814ad4307bf63a67`이다. weight SHA-256을 검사했고 Torch 2.14.1 / Transformers 5.18.0 / CPU float32 / 4 threads로 실행했다. 모델 로드 16.01초와 별도 warmup 68.84초는 케이스 지연에 넣지 않았다.

현재 정책과 최근 대화 이력을 JSON state로 전달했다. 최대 네 메시지를 각 500자까지 제공하고 정답·tags·notes는 전달하지 않았다. threshold는 결과를 보기 전에 0.5로 고정했다. 인사와 첨부 shortcut은 현재 순서와 동일하다. `max_len=8192`, `head_max_len=512`이며 네 질문씩 실행했다. 관측의 SDK truncation flag는 모두 false다. 추가 토큰 예산 검사에서 가장 긴 option은 30토큰, instruction은 118토큰이었고 잘리는 head는 없었다.

CPU 메모리를 위해 질문을 네 개씩 처리했으며, 같은 PC에서 offline 검증도 병행했다. 따라서 이 지연은 현재 실험 실행기의 관측이고, 최적화된 Laya GPU 서비스와 nano/Jev API를 공정하게 비교한 지연이 아니다. 실행 당시 source hash와 로컬 source snapshot을 보관했다. 실행 뒤 추가한 잘림 검사와 집계 개선을 당시 코드에서 실행한 것으로 소급 주장하지 않는다.

모델 판단 열 사례의 intent는 모두 crud였고, 모든 도구의 Noul 값이 선택 threshold를 넘었다. 입력에 긴 정책과 많은 도구 이름을 넣는 구성이 요청과 규칙을 구분하는 데 맞지 않을 가능성을 우선 조사한다. 이것은 관측에서 도출한 가설이다.

native 확률 열 사례의 다중분류 intent Brier는 1.098이다. required 양성/forbidden 음성 49개 라벨만 사용한 도구 Brier는 0.493이다. optional과 미지정 도구를 음성 정답으로 가정하지 않았으며, 이 작은 개발 자료로 일반적인 calibration 성능을 주장하지 않는다.

## 짧은 입력 진단

본 평가 완료 전, state를 짧은 요청 문장으로 바꾸고 영어로 쓴 intent와 세 개 도구 질문을 따로 확인했다. [입력](evaluations/decision-routing-20261003/focused-input.json)과 [응답](evaluations/decision-routing-20261003/focused-result.json)을 보관한다. 두 문항의 프로파일은 본 평가와 다르고, 모델 로드 뒤 첫 호출을 포함하므로 본 평가 점수나 p50에 합치지 않는다.

| 요청 | 관측 |
|---|---|
| 등록 장부 이름 목록 | list_tables 0.491, delete_rows 0.214. intent는 general로 잘못 분류 |
| 날짜별 주문 건수 꺾은선 | generate_chart 0.852, delete_rows 0.033. intent는 general로 잘못 분류 |

네 질문의 CPU 호출은 약 0.49초와 0.52초였다. 짧은 표현에서는 일부 도구를 구분했지만 intent와 경계 판단은 해결되지 않았다. 질문 수·state·언어가 함께 달라 원인을 분리한 ablation이나 속도 우위 근거가 아니다.

## 다음 실험

먼저 새 development run에서 짧은 state와 질문별 업무 조건을 시험하고, 한국어/영어 instruction 및 Noul/이진 Choice를 한 요소씩 비교한다. 현재 P0 원시 응답을 threshold 조정으로 덮어쓰지 않는다. 개선된 protocol은 nano A1에도 동일하게 적용해야 backend 효과와 질문 구조 효과를 구분할 수 있다.

사용 가능한 OpenAI 프로젝트와 Jev 키가 준비되면 같은 frozen dataset·질문·정책으로 A0/A1/B0/C0를 새로 interleave한다. 그 뒤 사람 검토, calibration/selection/confirmation, 전체 업무 pilot과 최종 Test를 진행한다. 현재 브랜치의 기본 서비스 라우터는 계속 기존 nano를 사용한다.
