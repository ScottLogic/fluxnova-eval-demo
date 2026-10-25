"""FastAPI app factory for ui-api.

Routers are one per concern (regression, workflow, evals), each wrapping the
existing core packages as a library/CLI rather than embedding API code inside
them — see UI_PROPOSAL.md's "Implementation plan" section.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ui_api.config import UiApiConfig
from ui_api.routers import evals, regression, workflow


def create_app(config: UiApiConfig | None = None) -> FastAPI:
    config = config or UiApiConfig()
    app = FastAPI(title="ui-api")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(regression.router)
    app.include_router(workflow.router)
    app.include_router(evals.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
