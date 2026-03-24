.PHONY: cli dev

cli:
	cd src && python -m core.agent.cli

dev:
	uvicorn src.api.app:app --reload
