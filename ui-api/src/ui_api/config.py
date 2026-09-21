"""Configuration for ui-api.

All settings are simple hardcoded defaults below, overridable via environment
variables (see ``main.py``) — mirrors the approach taken by
eval-service-worker/config.py and eval-trace-listener/config.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Origins the Vite dev server (frontend/) runs on — see frontend/vite.config.ts.
DEFAULT_CORS_ORIGINS = ["http://localhost:5173"]


@dataclass
class UiApiConfig:
    cors_origins: list[str] = field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
