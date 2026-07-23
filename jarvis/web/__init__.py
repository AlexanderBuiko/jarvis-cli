"""
jarvis.web — a minimal browser UI over the same command logic the REPL runs.

Exists so Level-2 smoke has a real clickable interface: a browser driver
(Playwright / Browser MCP) opens the page, fills a form, clicks, and checks the
result. It duplicates a slice of the CLI (config + tasks), reusing ``_dispatch``
so the web UI and the terminal run identical logic.

  server.py    the stdlib http.server backend + agent wiring
  __main__.py  `python -m jarvis.web` — start the server
  static/      the single-page front-end
"""

from .server import serve

__all__ = ["serve"]
