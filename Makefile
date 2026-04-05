.PHONY: up down logs chat ps bootstrap cli dev

bootstrap:
	mkdir -p ~/.heartclaw
	cd src && python -c "from config.settings import ensure_heartclaw_dirs; ensure_heartclaw_dirs()"

up:
	mkdir -p $${HOME}/.heartclaw/tiangong/codex
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
	cd src && python -m core.agent.cli

dev:
	uvicorn src.api.app:app --reload
