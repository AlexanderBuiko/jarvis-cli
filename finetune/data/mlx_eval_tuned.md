# Local eval (tuned) — mlx-community/Qwen2.5-7B-Instruct-4bit

- adapter: finetune/mlx_adapters
- examples: 13
- **accuracy: 85%**
- **format clean: 100%**

| # | reference | predicted | raw | ok |
|---|---|---|---|---|
| 1 | `this_week` | `urgent_now` | `urgent_now` | ❌ |
| 2 | `urgent_now` | `urgent_now` | `urgent_now` | ✅ |
| 3 | `today` | `today` | `today` | ✅ |
| 4 | `this_week` | `this_week` | `this_week` | ✅ |
| 5 | `today` | `today` | `today` | ✅ |
| 6 | `urgent_now` | `urgent_now` | `urgent_now` | ✅ |
| 7 | `urgent_now` | `urgent_now` | `urgent_now` | ✅ |
| 8 | `ignore` | `ignore` | `ignore` | ✅ |
| 9 | `today` | `today` | `today` | ✅ |
| 10 | `this_week` | `ignore` | `ignore` | ❌ |
| 11 | `ignore` | `ignore` | `ignore` | ✅ |
| 12 | `ignore` | `ignore` | `ignore` | ✅ |
| 13 | `ignore` | `ignore` | `ignore` | ✅ |
