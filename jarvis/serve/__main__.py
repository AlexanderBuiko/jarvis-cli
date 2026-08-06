"""
Run the LLM core server: ``python -m jarvis.serve``.

Reads ``JARVIS_LLM_CORE_HOST`` / ``JARVIS_LLM_CORE_PORT`` (defaults 127.0.0.1:8901)
and ``JARVIS_LLM_PROVIDER``. Binds to localhost by default — exposing it is a
deployment decision, not a default. Do not set ``JARVIS_LLM_GATEWAY_URL`` in this
process: the core calls the provider directly, and routing it back through a gateway
that forwards here would loop.
"""

from __future__ import annotations

import logging
import os

from .server import build_server, core_from_env


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    host = os.environ.get("JARVIS_LLM_CORE_HOST", "127.0.0.1")
    port = int(os.environ.get("JARVIS_LLM_CORE_PORT", "8901"))
    app = core_from_env()
    server = build_server(host, port, app)
    logging.getLogger("jarvis.serve").info(
        "LLM core on http://%s:%d  (provider=%s)", host, port, app.default_provider)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
