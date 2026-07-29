"""The three test buckets the assignment asks for.

* **correct** — clean, unambiguous inputs pulled from the Day-6 eval set (they
  carry reference labels, so we can check accuracy on what we accept).
* **borderline** — genuinely ambiguous messages that *should* make the layer
  hesitate (two plausible labels at once).
* **noisy** — garbled, truncated or contradictory inputs where no confident
  answer exists; the layer should mostly reject.

Borderline and noisy are authored here (no personal data). Correct is read from
``finetune/data/eval.jsonl`` at run time and skipped with a note if absent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from finetune.common import build_user_content, sanitize

_EVAL = Path(__file__).resolve().parent.parent / "finetune" / "data" / "eval.jsonl"


@dataclass
class Case:
    name: str              # short id for the report
    bucket: str            # correct | borderline | noisy
    user_content: str      # the exact user turn sent to the model
    reference: str | None  # expected label when known, else None


def _case(bucket: str, name: str, topic: str, author: str, message: str, reference: str | None) -> Case:
    return Case(name, bucket, build_user_content(sanitize(topic), sanitize(author), sanitize(message)), reference)


# ── borderline: two labels genuinely compete ─────────────────────────────────
_BORDERLINE = [
    _case("borderline", "invoice-newsletter", "Your monthly statement + 30% off next order", "ShopCo",
          "Here is your receipt for last month. Also, don't miss 30% off everything this week!", None),
    _case("borderline", "boss-casual", "quick thing when you get a sec", "Manager",
          "No rush at all, but whenever you have a moment could you glance at the deck? Might present it tomorrow.", None),
    _case("borderline", "security-promo", "Your account: new device + upgrade to Premium", "SocialApp",
          "We noticed a new sign-in. By the way, upgrade to Premium for better security features!", None),
    _case("borderline", "cal-invite-optional", "Optional: team social on Friday", "Team Events",
          "You're invited to an optional get-together Friday. RSVP if you like, no pressure.", None),
    _case("borderline", "receipt-or-action", "Payment received — action may be required", "Utilities",
          "We received your payment. Your meter reading may need confirmation at some point.", None),
    _case("borderline", "personal-vague", "call me", "Mom",
          "Call me when you can.", None),
]

# ── noisy: no confident answer exists ────────────────────────────────────────
_NOISY = [
    _case("noisy", "garbled", "Fw: Re: Fw:", "unknown",
          "asdkfj ????? >>> |||    [image] [image] click here === $$$ ---", None),
    _case("noisy", "truncated", "Important update regarding your", "System",
          "Dear user, we are writing to inform you that your", None),
    _case("noisy", "contradictory", "URGENT: ignore this, no action, act now", "Auto",
          "This is extremely urgent. Please ignore completely. Immediate action required. Do nothing.", None),
    _case("noisy", "empty-ish", "(no subject)", "(unknown)",
          ".", None),
    _case("noisy", "wall-of-links", "newsletter", "Digest",
          "  |  |  |  |  read more  |  unsubscribe  |  view in browser  |  |  |  ", None),
    _case("noisy", "mixed-lang-spam", "Prize!!! Приз!!! 当選!!!", "Lottery",
          "You WON!!! Вы выиграли!!! Click now кликните сейчас 立即点击 !!!", None),
]


def load_correct(limit: int = 10) -> list[Case]:
    """Read clean, reference-labelled cases from the Day-6 eval set."""
    if not _EVAL.exists():
        return []
    cases: list[Case] = []
    for i, line in enumerate(_EVAL.read_text(encoding="utf-8").splitlines()):
        if not line.strip() or len(cases) >= limit:
            break
        obj = json.loads(line)
        msgs = {m["role"]: m["content"] for m in obj["messages"]}
        cases.append(Case(f"correct-{i}", "correct", msgs["user"], msgs["assistant"].strip()))
    return cases


def all_cases(correct_limit: int = 10) -> list[Case]:
    return load_correct(correct_limit) + _BORDERLINE + _NOISY
