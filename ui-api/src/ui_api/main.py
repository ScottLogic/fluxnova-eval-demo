"""CLI entry point for ui-api.

Usage
-----
    ui-api
    ui-api --host 0.0.0.0 --port 8090
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable

import uvicorn

from ui_api.app import create_app
from ui_api.config import UiApiConfig

app = create_app()


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"UI_API_{name}", default)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the ui-api server backing the demo frontend. Every flag can "
        "also be set via a UI_API_<NAME> environment variable (e.g. UI_API_PORT)."
    )
    parser.add_argument(
        "--host",
        default=_env("HOST", "127.0.0.1"),
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(_env("PORT", "8090")),
        help="Port to bind to (default: 8090)",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    cors_origins_env = _env("CORS_ORIGINS")
    config = (
        UiApiConfig(cors_origins=cors_origins_env.split(","))
        if cors_origins_env
        else UiApiConfig()
    )
    uvicorn.run(create_app(config), host=args.host, port=args.port)


if __name__ == "__main__":
    main(sys.argv[1:])
