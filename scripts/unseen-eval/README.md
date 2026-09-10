# Phase 3: 새 파일·질문 평가

합성 CSV 7개와 XLSX 1개, 데이터 내 지시문을 포함한 Markdown 1개를 실제 보관함 API로 준비한다. `samples/unseen-v1/source.json`은 원시 합성 입력, `manifest.json`은 질문·독립 정답·채점 규칙이다. 실제 PG 파일은 사용하지 않는다.

실행 전 고정한 기준: 본 평가 30문항 중 **27개 이상**, 보완에 사용하지 않는 별도 10문항 중 **9개 이상**. 계정 경계 침범·선택 외 자료 집계·원본 변경·요청하지 않은 저장본 변경은 **0건**이어야 한다. 자동 판정과 설명 검토를 모두 확인하기 전에는 전체 통과로 표시하지 않는다.

```powershell
python -m pytest scripts/unseen-eval/test_oracle.py -q
# 자료 준비도 실제 임베딩을 호출한다.
python scripts/unseen-eval/run.py --env-file D:/Github/DATAEZ/.env
python scripts/unseen-eval/run.py --live-llm --suite main --env-file D:/Github/DATAEZ/.env
# 본 평가 보완을 마친 후 별도 10문항을 실행한다.
python scripts/unseen-eval/run.py --live-llm --suite holdout --env-file D:/Github/DATAEZ/.env
```

Docker의 `pgvector/pgvector:pg16`, Python API 의존성이 필요하다. 매번 이름과 소유 라벨을 붙인 loopback 전용 임시 PostgreSQL 컨테이너를 생성하고, 임의 포트의 API를 실행한다. 지속형 데모 DB에 접속하지 않는다. 종료 시 자신이 생성한 API와 컨테이너·임시 DB를 정리한다. 로그·원시 응답은 Git에서 제외된 `.local-test/unseen-eval/`에 보관한다.

`--cases N01,N03`은 부분 회귀다. 상태 변경 문항 S19–S24는 동일 대화의 앞선 상태가 필요하므로 모두 포함한다. 최초 결과를 덮어쓰지 않는다. 스크립트 실패와 제품 판정 실패를 구별하고, 자료/정답/채점 오류를 보완하면 이유·이전 해시와 재실행 범위를 공개 기록에 남긴다.

대부분은 실제 동기 메시지 HTTP 경로를, N04/B29/H03은 실제 스트리밍 HTTP 경로를 평가한다. 브라우저 40문항 검증으로 해석하지 않는다. 금액의 정확한 셀, 출처 테이블·파일 원본/누적 선택, 기간·필터·그룹·단위·차트와 저장 정의·이력·주기를 비교한다. 원본 DB 스냅샷과 내려받은 파일의 바이트 해시도 확인한다.

자료 준비의 임베딩 사용량과 질문별 모델·토큰·지연·저장소 가격표 기반 추정 비용을 구분한다. 추정치는 실제 청구액이나 최신 가격 보증이 아니다. 고정 날짜 조건을 사용하며, 실행일을 기준으로 기대값을 바꾸지 않는다.

파일 선택 중에는 기존 계약상 저장 지표 수정·복원을 지원하지 않으므로 S19–S24는 선택을 명시적으로 해제한 상태에서 연결 장부를 대상으로 진행한다. 본 평가의 성공이 파일 선택을 유지한 채 모든 수정 도구를 쓸 수 있다는 의미는 아니다.
