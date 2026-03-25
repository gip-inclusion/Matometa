.PHONY: dev dev-ollama up up-ollama up-eval down test lint format security ci

# --- Local development (venv) ---

## Start locally with cli backend (reads .env)
dev:
	.venv/bin/python3 -m web.pm & PID=$$!; \
	trap "kill $$PID 2>/dev/null" EXIT; \
	.venv/bin/python3 -m web.app

## Start locally with cli-ollama backend (ollama must be running)
dev-ollama:
	.venv/bin/python3 -m web.pm & PID=$$!; \
	trap "kill $$PID 2>/dev/null" EXIT; \
	AGENT_BACKEND=cli-ollama .venv/bin/python3 -m web.app

# --- Docker ---

## Start web app with cli backend (default)
up:
	docker compose up -d

## Start web app with cli-ollama backend + ollama container
up-ollama:
	AGENT_BACKEND=cli-ollama docker compose --profile ollama up -d

## Start web app (cli) + ollama container for running evals against both backends
up-eval:
	docker compose --profile ollama up -d

## Stop everything
down:
	docker compose --profile ollama down

# --- Quality ---

## Lint (ruff check + format check)
lint:
	uv run --frozen ruff check web/ lib/ scripts/ tests/
	uv run --frozen ruff format --check web/ lib/ scripts/ tests/

## Auto-format code
format:
	uv run --frozen ruff check --fix web/ lib/ scripts/ tests/
	uv run --frozen ruff format web/ lib/ scripts/ tests/

## Security checks (SAST + dependency audit)
security:
	uv run --frozen bandit -r web/ lib/ scripts/ -c pyproject.toml --severity-level medium --confidence-level high -q
	# pygments: CVE-2026-4539 — no fixed release on PyPI yet; drop --ignore-vuln when pygments>=2.19.3
	uv export --frozen --no-hashes --no-emit-project > /tmp/requirements.txt && uv run --frozen pip-audit -r /tmp/requirements.txt --ignore-vuln CVE-2026-4539

## Run all CI checks locally
ci: lint security test

# --- Tests ---

## test_metabase_answers requires live credentials and has no @pytest.mark.integration marker.
test:
	uv run --frozen pytest tests/ -q --tb=short -m "not integration" --ignore=tests/test_metabase_answers.py
