"""Keep the project's test gate scoped to ``tests/``.

``docs/day5-execution-loop/sandbox-seed/`` ships example ``test_*.py`` files as
part of a deliverable — they are meant to run *inside* that copied sandbox (where
``calckit`` is importable), not to be collected by jarvis-cli's own ``pytest``
run. Without this, plain ``pytest`` from the repo root would try to import them
and fail collection.
"""

collect_ignore_glob = ["docs/*"]
