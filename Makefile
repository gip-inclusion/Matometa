.PHONY: dev dev-ollama up up-ollama up-eval down test

# --- Local development (venv) ---

## Start locally with cli backend (reads .env)
dev:
	.venv/bin/python3 -m web.app

## Start locally with cli-ollama backend (ollama must be running)
dev-ollama:
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

# --- Tests ---

test:
	.venv/bin/pytest tests/
