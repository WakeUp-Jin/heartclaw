from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health, chat, webhook, card_callback, ws, juanzong


def create_app(*, lifespan: Any = None) -> FastAPI:
    app = FastAPI(
        title="HeartClaw",
        description="Lightweight AI Agent with Feishu as collaborative space",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(webhook.router)
    app.include_router(card_callback.router)
    app.include_router(ws.router)
    app.include_router(juanzong.router)

    return app
