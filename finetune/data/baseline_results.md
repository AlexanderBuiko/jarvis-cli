# Baseline — openai/gpt-4o-mini (no fine-tune)

- Examples: 10
- **Accuracy: 20%** (exact label match)
- **Format clean: 100%** (bare label, no prose)

| # | reference | prediction | correct | clean |
|---|---|---|---|---|
| 1 | `this_week` | `ignore` | ❌ | ✅ |
| 2 | `urgent_now` | `urgent_now` | ✅ | ✅ |
| 3 | `today` | `ignore` | ❌ | ✅ |
| 4 | `this_week` | `ignore` | ❌ | ✅ |
| 5 | `today` | `ignore` | ❌ | ✅ |
| 6 | `urgent_now` | `urgent_now` | ✅ | ✅ |
| 7 | `urgent_now` | `ignore` | ❌ | ✅ |
| 8 | `ignore` | `urgent_now` | ❌ | ✅ |
| 9 | `today` | `ignore` | ❌ | ✅ |
| 10 | `this_week` | `ignore` | ❌ | ✅ |
