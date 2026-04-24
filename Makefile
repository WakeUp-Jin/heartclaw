.PHONY: up down logs chat ps bootstrap cli dev web-dev web-build

bootstrap:
	mkdir -p ~/.heartclaw
	cd apps/ruyi-api && PYTHONPATH=src uv run python -c "from config.settings import ensure_heartclaw_dirs; ensure_heartclaw_dirs()"

up:
	mkdir -p $${HOME}/.heartclaw/tiangong/codex
	mkdir -p $${HOME}/.heartclaw/tiangong/kimi
	mkdir -p $${HOME}/.heartclaw/tiangong/opencode
	mkdir -p $${HOME}/.heartclaw/tiangong/opencode-config
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

chat:
	@curl -sS http://localhost:8000/api/chat \
	  -H 'Content-Type: application/json' \
	  -d '{"text":"$(TEXT)","chat_id":"local","open_id":"local"}'

ps:
	docker compose ps

cli:
	cd apps/ruyi-api && PYTHONPATH=src uv run python -m core.agent.cli

dev:
	cd apps/ruyi-api && PYTHONPATH=src uv run python src/main.py

web-dev:
	cd apps/web && npm run dev

web-build:
	cd apps/web && npm run build
