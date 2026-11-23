"""Entry point: ``python -m clipper``."""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="clipper", description="Clip Factory backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8756)
    parser.add_argument("--reload", action="store_true", help="dev autoreload")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()
    uvicorn.run(
        "clipper.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
