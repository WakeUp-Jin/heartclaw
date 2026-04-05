.PHONY: cli dev docker tiangong

cli:
	cd src && python -m core.agent.cli

dev:
	uvicorn src.api.app:app --reload

docker:
	mkdir -p ~/.pineclaw
	docker compose up --build

tiangong:
	mkdir -p ~/.pineclaw
	docker compose up --build tiangong
