# Message-priority classifier — labels & evaluation

Fine-tune target: given one incoming message (email), output **exactly one**
priority label and nothing else. Single axis: *when does this need my attention*.

## The four labels

Signals below reflect the operator's *actual* labelling of the real inbox, which
is the ground truth the dataset teaches — not an idealised rubric.

| Label | One-line definition | Typical signals (as labelled) |
|---|---|---|
| `urgent_now` | Needs action within hours; cost of delay is real. | Security/account alerts, sign-in warnings, 2FA/OTP, payment failed, **receipts and transactional documents**, overdue invoices, a reply that blocks someone. |
| `today` | Should be handled by end of day, but not this minute. | Product "action required" / API migrations, travel price alerts, personal shares (a shared doc/comment), same-day reply expected, a meeting request this week, delivery/ride reports. |
| `this_week` | Useful, non-blocking; batch it into a weekly pass. | Social-network notifications (LinkedIn), FYI digests, newsletters you actually read, location-sharing notices. |
| `ignore` | No action ever. Drop, or unsubscribe/spam downstream. | Marketing/promo blasts, cold outreach, event ads, automated noise, spam. |

Rules that keep labels consistent (this is what the model learns):

- **One label per message.** If it feels like two, pick the *more urgent* one.
- **Label by required timing, not by topic.** A newsletter you love is still
  `this_week`; a one-line "call me" from your bank is `urgent_now`.
- **The action (forward / digest / unsubscribe) is NOT part of the label.** The
  label is pure classification; the action is a downstream lookup added later.
- **When unsure between two neighbours, pick the calmer one** (`today` over
  `urgent_now`, `this_week` over `today`). Over-escalation is the worse error.

## "It got better" — evaluation criteria

Baseline = un-tuned `gpt-4o-mini` on 10 held-out eval examples. Compare against
the fine-tuned model on the same 10.

1. **Accuracy (primary).** Exact label match against the reference. This is the
   headline number.
2. **Format (secondary).** Output is *exactly* one of the four tokens — no
   sentence, no punctuation, no explanation. The base model tends to explain
   instead of labelling; the fine-tune should stop doing that. Measured as
   "fraction of outputs that are a clean bare label".
3. **Style — N/A.** Not a generation task; there is no prose to grade.

Success = fine-tuned accuracy clearly above baseline **and** format at or near
100% clean labels.

## Dataset shape

- ≥ 50 examples total, JSONL, one training object per line.
- ≥ 20% real (your reviewed inbox); the rest synthetic, modelled on the real ones.
- Balanced: aim for roughly equal counts per label. Real inboxes skew heavily to
  `ignore`/`this_week`; we deliberately balance so the model learns the boundary,
  not the base rate. (Imbalance is a named antipattern.)
- Every training object has the identical system prompt (below) — same format in
  every example is what the model locks onto.

System prompt used in every example:

    You are a message-priority classifier. Read the incoming message and reply
    with exactly one label and nothing else: urgent_now, today, this_week, or ignore.
