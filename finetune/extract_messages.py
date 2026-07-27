"""Pull your latest Gmail messages into a review file you curate by hand.

Step 1 of the dataset build. It writes ``review.json`` — a list of
``{topic, author, message, label}`` with ``label`` blank. You then delete the
rows you do not want, fill each remaining ``label`` with one of the four values
in CRITERIA.md, and hand the file back. Those become the *real* slice of the
dataset, and the synthetic examples are modelled on them.

stdlib only (``imaplib``/``email``) — no new dependency. Credentials come from
env vars; nothing is hardcoded and no secret is ever written to disk:

    JARVIS_IMAP_USER      your full Gmail address
    JARVIS_IMAP_PASSWORD  a Gmail *app password* (not your normal password)
    JARVIS_IMAP_HOST      optional, defaults to imap.gmail.com

Run:  python -m finetune.extract_messages --count 50
"""

from __future__ import annotations

import argparse
import email
import json
import os
import re
import sys
from email.header import decode_header, make_header
from email.utils import parseaddr
from imaplib import IMAP4_SSL
from pathlib import Path

_DEFAULT_OUT = Path(__file__).parent / "data" / "review.json"
_MAX_BODY_CHARS = 4000  # keep review file readable; length filtering happens in split
_HTML_TAG = re.compile(r"<[^>]+>")
_WS_RUNS = re.compile(r"[ \t]+")
_BLANK_RUNS = re.compile(r"\n\s*\n\s*\n+")


# ── Header / body decoding ───────────────────────────────────────────────────

def _decode_header(raw: str | None) -> str:
    """RFC 2047 header (``=?utf-8?...?=``) → plain text, never raising."""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:  # a malformed header must not kill the whole run
        return raw.strip()


def _extract_body(msg: email.message.Message) -> str:
    """First readable text of a message: prefer text/plain, fall back to stripped HTML."""
    plain: str | None = None
    html: str | None = None
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition", "").lower().startswith("attachment"):
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and html is None:
            html = text
    body = plain if plain is not None else (_HTML_TAG.sub(" ", html) if html else "")
    return _clean(body)


def _clean(text: str) -> str:
    """Collapse whitespace and blank-line runs, then truncate for review."""
    text = _WS_RUNS.sub(" ", text.replace("\r\n", "\n"))
    text = _BLANK_RUNS.sub("\n\n", text).strip()
    if len(text) > _MAX_BODY_CHARS:
        text = text[:_MAX_BODY_CHARS].rstrip() + " […]"
    return text


# ── Fetch ────────────────────────────────────────────────────────────────────

def _latest_uids(imap: IMAP4_SSL, count: int) -> list[bytes]:
    """UIDs of the newest ``count`` messages in the selected folder, newest first."""
    typ, data = imap.uid("search", None, "ALL")
    if typ != "OK":
        raise RuntimeError(f"IMAP search failed: {typ}")
    uids = data[0].split()
    return list(reversed(uids[-count:]))


def fetch_messages(host: str, user: str, password: str, folder: str, count: int) -> list[dict]:
    """Connect, fetch the newest ``count`` messages, return review rows."""
    rows: list[dict] = []
    with IMAP4_SSL(host) as imap:
        imap.login(user, password)
        imap.select(folder, readonly=True)  # readonly: never touch the real mailbox
        for uid in _latest_uids(imap, count):
            typ, msg_data = imap.uid("fetch", uid, "(RFC822)")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            name, addr = parseaddr(_decode_header(msg.get("From")))
            rows.append({
                "topic": _decode_header(msg.get("Subject")) or "(no subject)",
                "author": name or addr or "(unknown)",
                "message": _extract_body(msg),
                "label": "",  # you fill this: urgent_now | today | this_week | ignore
            })
    return rows


# ── Entry point ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull latest Gmail messages into a review file.")
    parser.add_argument("--count", type=int, default=50, help="how many recent messages (default 50)")
    parser.add_argument("--folder", default="INBOX", help="IMAP folder (default INBOX)")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="output review file")
    args = parser.parse_args(argv)

    user = os.environ.get("JARVIS_IMAP_USER")
    password = os.environ.get("JARVIS_IMAP_PASSWORD")
    host = os.environ.get("JARVIS_IMAP_HOST") or "imap.gmail.com"
    if not user or not password:
        print("error: set JARVIS_IMAP_USER and JARVIS_IMAP_PASSWORD (Gmail app password)", file=sys.stderr)
        return 2

    try:
        rows = fetch_messages(host, user, password, args.folder, args.count)
    except Exception as exc:  # noqa: BLE001 — surface any IMAP/network failure cleanly
        print(f"error: could not fetch messages: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} messages to {args.out}")
    print("next: prune rows you don't want, fill each empty \"label\", then hand the file back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
