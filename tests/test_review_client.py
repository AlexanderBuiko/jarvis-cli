"""Tests for the reactive PR-review client (jarvis/review/)."""

import subprocess

import requests

from jarvis.review import client


def _run(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


# ── Context resolution ────────────────────────────────────────────────────────


def test_resolve_context_from_args(monkeypatch):
    for var in ("GITHUB_REPOSITORY", "GITHUB_EVENT_PATH"):
        monkeypatch.delenv(var, raising=False)
    ctx = client.resolve_context(base="main", head="feature", repo="me/proj", pr=7)
    assert (ctx.repo, ctx.pr_number, ctx.base, ctx.head) == ("me/proj", 7, "main", "feature")


def test_resolve_context_from_action_event(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text('{"pull_request": {"number": 42, "base": {"ref": "main"}}}')
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widget")
    ctx = client.resolve_context(base=None, head=None, repo=None, pr=None)
    assert ctx.repo == "acme/widget"
    assert ctx.pr_number == 42
    assert ctx.base == "origin/main"
    assert ctx.head == "HEAD"


# ── Diff gathering ────────────────────────────────────────────────────────────


def test_gather_diff(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q")
    _run(repo, "git", "checkout", "-q", "-b", "main")  # deterministic base name
    (repo / "f.py").write_text("x = 1\n")
    _run(repo, "git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _run(repo, "git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base")
    _run(repo, "git", "checkout", "-q", "-b", "feature")
    (repo / "f.py").write_text("x = 2\n")
    _run(repo, "git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-aqm", "change")
    monkeypatch.chdir(repo)

    diff, files = client.gather_diff(client.ReviewContext(None, None, "main", "feature"))
    assert "f.py" in files
    assert "-x = 1" in diff and "+x = 2" in diff


# ── Endpoint derivation ───────────────────────────────────────────────────────


def test_review_endpoint_from_mcp_url(monkeypatch):
    monkeypatch.delenv("REVIEW_SERVER_URL", raising=False)
    monkeypatch.setenv("JARVIS_MCP_URL", "http://host:8080/mcp")
    assert client._review_endpoint() == "http://host:8080/review"


def test_review_endpoint_missing(monkeypatch):
    monkeypatch.delenv("REVIEW_SERVER_URL", raising=False)
    monkeypatch.delenv("JARVIS_MCP_URL", raising=False)
    import pytest
    with pytest.raises(client.ReviewClientError):
        client._review_endpoint()


# ── Request + formatting ──────────────────────────────────────────────────────


def test_request_review_posts_and_returns(monkeypatch):
    monkeypatch.setenv("REVIEW_SERVER_URL", "http://localhost:8080")
    captured = {}

    class _Resp:
        status_code = 200
        text = "{}"
        def json(self):
            return {"review": "### Potential bugs\nNone.", "verdict": "approve", "usage": {}}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr(requests, "post", fake_post)
    out = client.request_review("some diff", ["f.py"], "me/proj")
    assert captured["url"] == "http://localhost:8080/review"
    assert captured["json"]["changed_files"] == ["f.py"]
    assert out["verdict"] == "approve"


def test_format_comment_has_body_and_footer():
    result = {"review": "### Potential bugs\nNone found.", "verdict": "approve",
              "model": "google/gemini-2.5-flash",
              "usage": {"total_tokens": 1234, "latency_ms": 2500}}
    body = client.format_comment(result)
    assert "AI Code Review" in body
    assert "### Potential bugs" in body
    assert "1234 tokens" in body
    assert "a human decides the merge" in body


# ── Orchestration (dry-run, no git/network) ───────────────────────────────────


def test_run_dry_run(monkeypatch):
    monkeypatch.setattr(client, "gather_diff", lambda ctx: ("some diff", ["f.py"]))
    monkeypatch.setattr(client, "request_review",
                        lambda diff, files, repo: {"review": "### Potential bugs\nNone.",
                                                   "verdict": "approve", "model": "m", "usage": {}})
    out = client.run(base="main", head="feature", repo="me/proj", pr=1, dry_run=True)
    assert out.startswith("[DRY_RUN]")
    assert "AI Code Review" in out


def test_run_empty_diff(monkeypatch):
    monkeypatch.setattr(client, "gather_diff", lambda ctx: ("", []))
    out = client.run(base="main", head="feature", repo="me/proj", pr=1, dry_run=True)
    assert "No changes to review" in out
