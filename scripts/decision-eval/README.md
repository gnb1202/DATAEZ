# DATAEZ 의사결정 라우터 개발 실험

현재 라우터 A0, 동일 정책을 원자 질문으로 나눈 nano A1, Laya multilingual B0, Jev C0를 실제 호출한다. **운영 라우터 선택을 바꾸는 기능은 아니다.** 먼저 개발용 라우팅 결과를 확인한다. 전체 업무의 SQL·차트·DB 상태 평가와 최종 holdout은 [평가 설계](../../docs/DECISION_MODEL_EVALUATION_PLAN.md)의 후속 단계다.

## 실행

저장소 루트에서 실행한다. API 기본/개발 의존성과 Python 3.12가 필요하다. 키는 프로세스 환경변수 또는 Git에서 제외된 `.env.local`/`.env`에서 읽는다. 프로세스 환경변수가 우선하고 `.env.local`이 `.env`보다 우선한다. 키나 인증 헤더는 산출물에 저장하지 않는다.

```powershell
# 모델·DB·네트워크 호출 없이 입력 계약과 사례 검사
python scripts/decision-eval/run.py --validate-only
python -m pytest api/tests/test_decision_models.py scripts/decision-eval/test_report.py -q

# OpenAI 실제 호출: OPENAI_API_KEY 필요. 먼저 한 번의 접근/크레딧 probe를 기록한다.
python scripts/decision-eval/run.py --arms current atomic

# Jev 실제 호출: TYPESAFE_API_KEY 필요, HTTP API 사용, 별도 SDK 설치 불필요
python scripts/decision-eval/run.py --arms jev
```

Laya는 별도 환경에 설치해 API 배포 이미지에 Torch를 추가하지 않는다. 공개 모델 다운로드에 Hugging Face 토큰은 필수가 아니다. 다음은 CPU 실행 예시다. `--device cuda`는 실제 CUDA 환경에서만 사용하고, CPU와 GPU 측정은 별도 실행으로 기록한다.

```powershell
python -m venv --system-site-packages .local-test/decision-model-eval/venv
uv pip install --python .local-test/decision-model-eval/venv/Scripts/python.exe -r scripts/decision-eval/requirements-laya.txt

# 선택 사항: 아래 명령으로 고정된 모델을 먼저 받아 두면 로컬 경로로 실행할 수 있다.
hf download convaiinnovations/laya-multilingual --revision e4e9ddf21a7b1903b7acffd8814ad4307bf63a67 --local-dir .local-test/decision-model-eval/laya-multilingual --include 'rl_agent_config.json' 'model.safetensors' 'tokenizer/*' 'encoder/*'

.local-test/decision-model-eval/venv/Scripts/python.exe scripts/decision-eval/run.py --arms laya --laya-path .local-test/decision-model-eval/laya-multilingual

# 각 provider가 준비된 경우, 같은 사례를 섞어서 비교
.local-test/decision-model-eval/venv/Scripts/python.exe scripts/decision-eval/run.py --arms current atomic laya jev --laya-path .local-test/decision-model-eval/laya-multilingual

# 저장된 기록만으로 재집계: 키·모델·네트워크 불필요
python scripts/decision-eval/report.py --run .local-test/decision-model-eval/runs/<run-id>
```

## 비교 계약

- 신규 12개 사례는 **Codex가 계약에 맞춰 검토한 development 자료**다. 사람 승인이나 독립 holdout이라고 주장하지 않는다. 인사·첨부 shortcut 두 사례와 모델을 호출하는 열 사례를 구분한다.
- A0는 현재 프롬프트·재시도·history 창을 그대로 사용한다. A1/B0/C0는 같은 state, 네 가지 intent Choice, 도구별 Noul 32개를 사용한다. 도구 threshold는 사전 고정한 0.5다. 후속 튜닝은 새 run으로 분리한다.
- 최근 네 user/assistant 메시지를 각각 500자까지 제공한다. expected labels, notes, tags는 모델 state에 포함하지 않는다. 첨부파일 유무와 순수 인사 shortcut 순서는 현재 코드와 같다.
- A1의 도구 출력은 boolean이며 **모델 확률이 아니다**. B0/C0의 원시 확률을 보관하고 SDK confidence를 정답 확률로 대신 쓰지 않는다.
- Laya SDK `0.3.24`, 모델 revision `e4e9ddf…`, weight SHA-256을 고정한다. 로컬 경로도 weight digest를 검사한다. max_len=8192/head_max_len=512이며 instruction/options/state 잘림을 실행 전에 거부한다. CPU 메모리를 제한하기 위해 질문 네 개씩 실행하므로 최적화된 GPU 병렬 지연과 비교하지 않는다.
- Jev는 `jev-1.13.0` 요청/응답 버전을 검사한다. HTTP 요청의 자동 재시도는 없다. A0와 A1은 기존 OpenAI SDK의 전송 재시도를 사용하며, A0의 라우터 재시도도 유지한다.
- 원시 도구와 현재 agent의 동일한 의존 도구 보완 결과(`effective_tools_before_scope`)를 기록한다. 선택 파일·가게의 worker scope 필터와 실제 worker 실행은 이 단계에서 수행하지 않는다. forbidden **선택**을 실제 DB 변경으로 표현하지 않는다.

## 산출물과 실패

각 run은 새 폴더에 생성한다. 실행 전 dataset bytes/hash, source snapshots/hashes, git 상태, schedule, threshold, 모델 설정과 Python 패키지 버전을 잠근다. `observations.jsonl`은 관측마다 flush하고, `summary.json`은 실행 집계, `scorecard.json/md`는 offline 재집계 결과다. 모델 로드와 별도 warmup 시간은 케이스 지연에서 제외해 별도로 기록한다.

명시적 degraded 목록도 fallback으로 센다. 비용이 일부라도 미확인이면 합계는 null이다. Laya의 전기/호스팅은 미측정으로 남긴다. 공식 단가 확인일과 출처는 manifest에 기록하며, A0는 캐시 토큰을 수집하지 않으므로 전체 입력 단가의 상한 추정으로 표시한다. A1은 반환된 캐시 토큰을 반영한다. 실제 청구서와 동일하다는 주장은 하지 않는다.

접근/크레딧 오류는 OpenAI probe 한 번으로 확인하고 해당 backend를 unavailable로 기록한다. 설정 실패와 미실행 사례는 계획 분모에서 지우지 않는다. unavailable backend의 성능은 N/A이고, 실행이 불완전하거나 케이스 오류가 있으면 종료 코드 2다. 전송 예외의 payload는 기록하지 않고 오류 유형만 남긴다.

offline Brier는 native 확률이 있는 케이스만 다룬다. 도구 Brier는 required 양성/forbidden 음성만 사용하며 optional과 미지정 도구를 음성 정답으로 가정하지 않는다. 지표 지원 문항 수와 label 수를 함께 기록한다. 12개 개발 자료로 보정 성능이나 서비스 도입 우위를 확정하지 않는다.
