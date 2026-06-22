"""Entry point: ``python -m jarvis.mcp`` → the MCP CLI."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
