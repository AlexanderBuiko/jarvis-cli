"""
Reactive PR-review client (the CI side of the AI code reviewer).

Run as ``python -m jarvis.review`` from a GitHub Action. It holds the GitHub token
and does all GitHub I/O — gather the PR diff, ask the remote ``/review`` brain to
review it, and post the review back as a PR comment. The brain (jarvis-mcp-server)
holds no GitHub credentials; this client is the only thing that talks to GitHub
(the "Option A" split).

See ``client.py`` for the pieces and ``__main__.py`` for the entrypoint.
"""

from .client import (
    ReviewContext,
    gather_diff,
    request_review,
    format_comment,
    post_comment,
    run,
)

__all__ = [
    "ReviewContext",
    "gather_diff",
    "request_review",
    "format_comment",
    "post_comment",
    "run",
]
