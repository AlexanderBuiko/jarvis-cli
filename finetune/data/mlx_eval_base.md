# Local eval (base) — mlx-community/Qwen2.5-7B-Instruct-4bit

- adapter: (none)
- examples: 13
- **accuracy: 38%**
- **format clean: 100%**

| # | reference | predicted | raw | ok |
|---|---|---|---|---|
| 1 | `this_week` | `today` | `today` | ❌ |
| 2 | `urgent_now` | `urgent_now` | `urgent_now` | ✅ |
| 3 | `today` | `ignore` | `ignore` | ❌ |
| 4 | `this_week` | `ignore` | `ignore` | ❌ |
| 5 | `today` | `today` | `today` | ✅ |
| 6 | `urgent_now` | `urgent_now` | `urgent_now` | ✅ |
| 7 | `urgent_now` | `ignore` | `ignore` | ❌ |
| 8 | `ignore` | `urgent_now` | `urgent_now` | ❌ |
| 9 | `today` | `today` | `today` | ✅ |
| 10 | `this_week` | `ignore` | `ignore` | ❌ |
| 11 | `ignore` | `ignore` | `ignore` | ✅ |
| 12 | `ignore` | `urgent_now` | `urgent_now` | ❌ |
| 13 | `ignore` | `today` | `today` | ❌ |
