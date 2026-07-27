"""OpenAI fine-tuning client: upload → create job → poll status.

Step 6, the assignment's "prepare the code, don't launch it yet". This is the
full automation — it uploads the training file, opens a fine-tuning job, and
polls until the job leaves a running state — but nothing fires unless you run it
with ``--go``. Without that flag it does a dry run: it prints exactly what it
would send and exits, so the code is reviewable without spending anything.

Reads ``OPENAI_API_KEY`` from the environment.

Dry run:  python -m finetune.upload_client
Launch:   python -m finetune.upload_client --go
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests

_DATA = Path(__file__).parent / "data"
_BASE = "https://api.openai.com/v1"
_TIMEOUT = 60
_TERMINAL = {"succeeded", "failed", "cancelled"}


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def upload_file(path: Path, api_key: str) -> str:
    """Upload a JSONL training file; return the file id."""
    with path.open("rb") as fh:
        resp = requests.post(
            f"{_BASE}/files",
            headers=_headers(api_key),
            files={"file": (path.name, fh, "application/jsonl")},
            data={"purpose": "fine-tune"},
            timeout=_TIMEOUT,
        )
    _raise_for_status(resp)
    return resp.json()["id"]


def create_job(file_id: str, model: str, api_key: str) -> str:
    """Create a fine-tuning job over an uploaded file; return the job id."""
    resp = requests.post(
        f"{_BASE}/fine_tuning/jobs",
        headers=_headers(api_key),
        json={"training_file": file_id, "model": model},
        timeout=_TIMEOUT,
    )
    _raise_for_status(resp)
    return resp.json()["id"]


def poll(job_id: str, api_key: str, interval: int = 30) -> dict:
    """Poll a job until it reaches a terminal state; return the final job object."""
    while True:
        resp = requests.get(f"{_BASE}/fine_tuning/jobs/{job_id}", headers=_headers(api_key), timeout=_TIMEOUT)
        _raise_for_status(resp)
        job = resp.json()
        status = job.get("status")
        print(f"  job {job_id}: {status}")
        if status in _TERMINAL:
            return job
        time.sleep(interval)


def _raise_for_status(resp: requests.Response) -> None:
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI {resp.status_code}: {resp.text[:300]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload + launch an OpenAI fine-tune job.")
    parser.add_argument("--train", type=Path, default=_DATA / "train.jsonl")
    parser.add_argument("--model", default="gpt-4o-mini-2024-07-18",
                        help="base model to fine-tune")
    parser.add_argument("--go", action="store_true", help="actually upload and launch (default: dry run)")
    args = parser.parse_args(argv)

    if not args.train.exists():
        print(f"error: {args.train} not found — run split first", file=sys.stderr)
        return 2

    if not args.go:
        print("DRY RUN — nothing sent. Would do:")
        print(f"  1. upload {args.train} (purpose=fine-tune)")
        print(f"  2. create fine_tuning job on base model {args.model}")
        print("  3. poll every 30s until succeeded/failed/cancelled")
        print("Re-run with --go to launch for real.")
        return 0

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("error: set OPENAI_API_KEY", file=sys.stderr)
        return 2

    try:
        file_id = upload_file(args.train, api_key)
        print(f"uploaded: {file_id}")
        job_id = create_job(file_id, args.model, api_key)
        print(f"job created: {job_id}")
        job = poll(job_id, api_key)
    except Exception as exc:  # noqa: BLE001 — surface API/network failure cleanly
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if job.get("status") == "succeeded":
        print(f"done. fine-tuned model: {job.get('fine_tuned_model')}")
        return 0
    print(f"job ended: {job.get('status')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
