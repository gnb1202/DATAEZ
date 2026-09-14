# Developer entry points. The split matters: `test` and `eval-validate` need
# no API key and run in CI, while `eval` spends real tokens and is run on
# demand before merging a change to routing or prompts.

.PHONY: test eval-validate eval eval-report quality-validate quality-smoke quality-full

test:
	python -m pytest tests/ -q

# Offline: schema-checks the golden dataset without calling a model.
eval-validate:
	python -m app.eval.run --validate-only

# Live: one orchestrator call per golden case. Exits non-zero if a gate fails.
eval:
	python -m app.eval.run

# Live, writing a scorecard for a PR body.
eval-report:
	python -m app.eval.run --out ../eval-report.md --json-out ../eval-report.json

# Full backend contracts (actual HTTP/DB/model/graph); run at repository root.
quality-validate:
	cd .. && python scripts/agent-quality/run.py validate
	cd .. && python -m pytest scripts/agent-quality -q

quality-smoke:
	cd .. && python scripts/agent-quality/run.py live --suite smoke

quality-full:
	cd .. && python scripts/agent-quality/run.py live --suite full
