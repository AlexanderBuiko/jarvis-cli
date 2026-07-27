"""Synthetic examples that balance and diversify the real inbox slice.

Modelled on the *real* labels the operator assigned (see review → real.jsonl),
not on the draft rubric: security/account/receipt mail is ``urgent_now``,
product "action required" / travel price alerts / personal shares are ``today``,
social-network notifications and FYI digests are ``this_week``, pure promo is
``ignore``. Senders here are deliberately different from the real set's dominant
three (Hume, LinkedIn, Aviasales) so no single source defines a class.

Kept as source (not a checked-in JSONL) so the synthetic half is reviewable and
regenerable: ``python -m finetune.synthetic_data`` writes ``data/synthetic.jsonl``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .common import training_object

# (topic, author, message, label) — authored, not scraped.
_EXAMPLES: list[tuple[str, str, str, str]] = [
    # ── urgent_now: security / account / money / transactional ────────────────
    ("New sign-in from an unrecognized device", "Microsoft account",
     "We detected a sign-in to your account from a new device in Berlin. If this wasn't you, secure your account now.",
     "urgent_now"),
    ("Your payment could not be processed", "Stripe",
     "The card on file for your subscription was declined. Update your payment method to avoid service interruption.",
     "urgent_now"),
    ("Verification code: 448192", "Bank of Astana",
     "Your one-time code is 448192. Enter it to confirm the transfer of $1,200. Do not share this code with anyone.",
     "urgent_now"),
    ("Receipt for your order #A-77413", "Kaspi",
     "Thank you for your purchase. Attached is your electronic receipt for 34,900 KZT paid on July 27.",
     "urgent_now"),
    ("Unusual activity detected on your card", "Visa Alerts",
     "A charge of $312 at an online merchant was flagged as unusual. Reply YES if this was you, otherwise call us immediately.",
     "urgent_now"),
    ("Password reset requested", "GitHub",
     "We received a request to reset your password. If you did not make this request, your account may be compromised.",
     "urgent_now"),
    ("Счёт-фактура и акт по заказу №5521", "Тинькофф Бизнес",
     "Во вложении закрывающие документы по вашему заказу. Проверьте и подпишите до конца дня.",
     "urgent_now"),
    ("Your invoice is overdue — final notice", "DigitalOcean",
     "Invoice #99213 for $48.00 is 14 days overdue. Services will be suspended if payment is not received.",
     "urgent_now"),
    ("Two-factor authentication was disabled", "Google",
     "Two-step verification was just turned off for your account. If you didn't do this, review your security settings now.",
     "urgent_now"),
    ("Confirm your email to keep your account", "Notion",
     "Action required: confirm your email address within 24 hours or your workspace will be locked.",
     "urgent_now"),

    # ── today: action-required product / travel price / personal share ────────
    ("[Action Required] Migrate off the legacy API by Aug 1", "Twilio",
     "The v1 messaging endpoints retire on August 1. Update your integration to v2 to avoid downtime.",
     "today"),
    ("Price drop: Almaty → Istanbul now $184", "Skyscanner",
     "A route on your watchlist dropped by $46. Fares at this price usually don't last long.",
     "today"),
    ("Arina shared a spreadsheet with you", "Google Sheets",
     "Arina shared 'Q3 Challenge Tracker' with you and left a comment asking for your input.",
     "today"),
    ("Can you review my PR today?", "Dmitry K.",
     "Hey, I opened a pull request for the auth refactor. Could you take a look before standup tomorrow?",
     "today"),
    ("Your package is out for delivery", "DHL Express",
     "Your parcel will be delivered today between 2pm and 6pm. Someone must be present to sign for it.",
     "today"),
    ("Meeting request: architecture sync this Thursday", "Elena R.",
     "Proposing a 30-minute sync on Thursday to align on the pipeline design. Does 15:00 work for you?",
     "today"),
    ("Yandex Go — trip receipt for July 26", "Yandex Go",
     "Your ride from home to the airport is complete. Total: 3,450 KZT. Rate your driver in the app.",
     "today"),
    ("[Action needed] Renew your domain jarvis.dev", "Namecheap",
     "Your domain expires in 3 days. Renew now to keep it and avoid a redemption fee.",
     "today"),
    ("Your OpenRouter usage hit 80% of the cap", "OpenRouter Team",
     "You've used 80% of this month's credit. Top up or adjust routing to avoid interrupted requests.",
     "today"),

    # ── this_week: social notifications / FYI digests ─────────────────────────
    ("You appeared in 9 searches this week", "LinkedIn",
     "Your profile showed up in 9 searches. See who's looking and who's hiring in your network.",
     "this_week"),
    ("Your weekly Kotlin newsletter is here", "Kotlin Weekly",
     "Issue #412: coroutines deep-dive, a new serialization release, and three conference talks worth watching.",
     "this_week"),
    ("Ваше местоположение видит 1 человек", "Google Карты",
     "Напоминаем: вы делитесь геопозицией с одним контактом. Изменить настройки можно в любой момент.",
     "this_week"),
    ("Reddit: 12 new posts in r/MachineLearning", "Reddit",
     "Here's what's trending in communities you follow this week. Catch up when you have a moment.",
     "this_week"),
]


def build() -> list[dict]:
    return [training_object(topic, author, message, label)
            for topic, author, message, label in _EXAMPLES]


def main() -> int:
    out = Path(__file__).parent / "data" / "synthetic.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    objects = build()
    with out.open("w", encoding="utf-8") as fh:
        for obj in objects:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"wrote {len(objects)} synthetic examples to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
