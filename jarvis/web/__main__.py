"""
Entrypoint for the Jarvis web UI: ``python -m jarvis.web``.

    python -m jarvis.web                # serve on 127.0.0.1:8765
    python -m jarvis.web --port 9000

Opens a browser-drivable page over the same command logic the REPL runs — the
Level-2 smoke target. Ctrl-C to stop.
"""

from __future__ import annotations

import argparse

from .server import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jarvis.web",
                                     description="Minimal web UI over the Jarvis command logic.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)

    server = serve(port=args.port, host=args.host)
    print(f"Jarvis web UI on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
