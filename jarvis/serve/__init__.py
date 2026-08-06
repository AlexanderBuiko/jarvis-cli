"""
LLM core server — jarvis's metered model layer behind ``POST /v1/complete``.

Week-10 (Security), the third tier of the split: application → guarded gateway →
LLM core. Run it with ``python -m jarvis.serve``. See :mod:`jarvis.serve.server`.
"""

from __future__ import annotations

from .server import LLMCore, build_server, complete_one, core_from_env

__all__ = ["LLMCore", "build_server", "complete_one", "core_from_env"]
