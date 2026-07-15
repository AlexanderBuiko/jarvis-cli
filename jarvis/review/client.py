"""
The review client: resolve PR context → gather diff → call /review → post comment.

Kept dependency-light (stdlib + ``requests``, already a project dep) so it installs
and runs quickly on a CI runner. Every GitHub call uses the Action-provided
``GITHUB_TOKEN``; the ``/review`` call uses the server's ``X-API-Key``.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

import requests


class ReviewClientError(Exception):
    """A hard failure the CI step should surface (non-zero exit)."""


@dataclass
class ReviewContext:
    """Everything needed to review one PR, resolved from CLI args or the Action env."""

    repo: str | None          # "owner/name"
    pr_number: int | None
    base: str                 # git ref to diff against (e.g. "origin/main")
    head: str                 # git ref of the PR head (e.g. "HEAD")


# ── Context resolution ────────────────────────────────────────────────────────


def resolve_context(base: str | None, head: str | None, repo: str | None,
                    pr: int | None) -> ReviewContext:
    """Resolve PR context: explicit args win, else the GitHub Action environment.

    In a ``pull_request`` workflow, GitHub sets ``GITHUB_REPOSITORY`` and
    ``GITHUB_EVENT_PATH`` (a JSON file with the PR's number and base ref). Locally,
    pass ``--base``/``--head`` (and optionally ``--repo``/``--pr``).
    """
    repo = repo or os.environ.get("GITHUB_REPOSITORY")
    event = _load_event()
    pull = (event or {}).get("pull_request") or {}
    if pr is None:
        pr = pull.get("number")
    if base is None:
        base_ref = (pull.get("base") or {}).get("ref")
        base = f"origin/{base_ref}" if base_ref else "origin/main"
    if head is None:
        head = "HEAD"
    return ReviewContext(repo=repo, pr_number=pr, base=base, head=head)


def _load_event() -> dict | None:
    path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


# ── Diff gathering ────────────────────────────────────────────────────────────


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise ReviewClientError(f"git {' '.join(args)} failed: {(proc.stderr or '').strip()}")
    return proc.stdout


def gather_diff(ctx: ReviewContext) -> tuple[str, list[str]]:
    """Return (diff, changed_files) for the PR using a three-dot diff.

    ``base...head`` diffs from the merge-base, i.e. exactly what the PR introduces.
    """
    rng = f"{ctx.base}...{ctx.head}"
    diff = _git("diff", rng)
    files = [f for f in _git("diff", "--name-only", rng).splitlines() if f.strip()]
    return diff, files


# ── Review request ────────────────────────────────────────────────────────────


def _review_endpoint() -> str:
    """Resolve the server ``/review`` URL from env.

    ``REVIEW_SERVER_URL`` wins; else derive from ``JARVIS_MCP_URL`` (drop a trailing
    ``/mcp``, since ``/review`` is a plain route at the server root).
    """
    base = os.environ.get("REVIEW_SERVER_URL", "").strip()
    if not base:
        mcp_url = os.environ.get("JARVIS_MCP_URL", "").strip()
        if not mcp_url:
            raise ReviewClientError(
                "no server URL — set REVIEW_SERVER_URL=https://host (or JARVIS_MCP_URL)."
            )
        base = mcp_url.rstrip("/")
        if base.endswith("/mcp"):
            base = base[: -len("/mcp")]
    return base.rstrip("/") + "/review"


def request_review(diff: str, changed_files: list[str], repo: str | None) -> dict:
    """POST the diff to the server /review endpoint; return the review result."""
    if not diff.strip():
        raise ReviewClientError("empty diff — nothing to review")
    endpoint = _review_endpoint()
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("MCP_API_KEY", "").strip()
    if key:
        headers["X-API-Key"] = key
    try:
        resp = requests.post(
            endpoint, json={"diff": diff, "changed_files": changed_files, "repo": repo},
            headers=headers, timeout=180,
        )
    except requests.RequestException as exc:
        raise ReviewClientError(f"server unreachable at {endpoint}: {exc}") from exc
    if resp.status_code != 200:
        detail = resp.text[:300]
        raise ReviewClientError(f"server error (HTTP {resp.status_code}): {detail}")
    return resp.json()


# ── Comment formatting + posting ──────────────────────────────────────────────


def format_comment(result: dict) -> str:
    """Compose the PR comment: the review body + a small metrics/AI-disclosure footer."""
    review = (result.get("review") or "").strip() or "_(no review text returned)_"
    usage = result.get("usage") or {}
    parts = [f"model `{result.get('model', '?')}`"]
    if usage.get("total_tokens") is not None:
        parts.append(f"{usage['total_tokens']} tokens")
    if usage.get("latency_ms") is not None:
        parts.append(f"{usage['latency_ms']:.0f} ms")
    parts.append(f"verdict: {result.get('verdict', 'comment')}")
    footer = "🤖 AI code review · " + " · ".join(parts) + " · advisory, a human decides the merge"
    return f"## 🤖 AI Code Review\n\n{review}\n\n---\n{footer}"


def post_comment(repo: str, pr_number: int, body: str, token: str) -> str:
    """Post ``body`` as a PR comment via the GitHub API; return the comment URL."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resp = requests.post(url, json={"body": body}, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise ReviewClientError(f"failed to post comment: {exc}") from exc
    if resp.status_code not in (200, 201):
        raise ReviewClientError(f"comment post rejected (HTTP {resp.status_code}): {resp.text[:200]}")
    return resp.json().get("html_url", "(posted)")


# ── Orchestration ─────────────────────────────────────────────────────────────


def run(base: str | None = None, head: str | None = None, repo: str | None = None,
        pr: int | None = None, dry_run: bool | None = None) -> str:
    """Full flow: resolve context → gather diff → review → post (or print in dry-run).

    Returns a short status line. ``dry_run`` (or env ``DRY_RUN``) prints the comment
    instead of posting — used for local testing without a real PR.
    """
    if dry_run is None:
        dry_run = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

    ctx = resolve_context(base, head, repo, pr)
    diff, files = gather_diff(ctx)
    if not diff.strip():
        return "No changes to review (empty diff)."

    result = request_review(diff, files, ctx.repo)
    comment = format_comment(result)

    if dry_run:
        return f"[DRY_RUN] would comment on {ctx.repo}#{ctx.pr_number}:\n\n{comment}"

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not (ctx.repo and ctx.pr_number and token):
        # No PR/token to post to — surface the review rather than silently dropping it.
        return ("No GITHUB_TOKEN/PR context to post to; review follows:\n\n" + comment)
    url = post_comment(ctx.repo, ctx.pr_number, comment, token)
    return f"Posted AI review to {ctx.repo}#{ctx.pr_number}: {url}"
