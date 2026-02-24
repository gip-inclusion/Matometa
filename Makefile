.PHONY: dev dev-ollama up up-ollama up-eval down expert-up expert-down expert-logs expert-setup expert-run expert-bootstrap test

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

# --- Expert mode infrastructure ---

## Start Gitea + Coolify for expert mode
expert-up:
	docker compose -f docker-compose.expert.yml up -d

## Stop expert mode infrastructure
expert-down:
	docker compose -f docker-compose.expert.yml down

## Follow expert mode logs
expert-logs:
	docker compose -f docker-compose.expert.yml logs -f

## First-time expert mode setup (run after expert-up)
expert-setup:
	bash scripts/setup_expert_test.sh

## Run full expert stack (matometa + gitea + coolify)
expert-run:
	docker compose up -d
	docker compose -f docker-compose.expert.yml up -d

## One-command bootstrap (start stack + configure tokens)
expert-bootstrap:
	$(MAKE) expert-run
	bash scripts/setup_expert_test.sh
	docker compose up -d --build

# --- Tests ---

test:
	.venv/bin/pytest tests/
