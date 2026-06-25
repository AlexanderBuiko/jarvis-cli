"""Entry point: ``python -m jarvis.mcp`` → the MCP CLI."""

# Load .env files *before* importing cli/config — config.py reads
# JARVIS_MCP_URL at import time, so the env must be populated first.
from ..config.env_file import load_env_files

load_env_files()

from .cli import main  # noqa: E402 — intentional: must follow load_env_files()

if __name__ == "__main__":
    raise SystemExit(main())
