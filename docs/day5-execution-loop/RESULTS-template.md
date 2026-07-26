# Day-5 execution-loop results

Fill this in from the printed reports and the `.jarvis-loop/run-*.md` logs.

## Headline — how many in a row without a pause

| Run | Model | Streak (in a row) | Completed total | First-pass % | Avg time/task | Broke on → why |
|-----|-------|-------------------|-----------------|--------------|---------------|----------------|
| 1 — cloud, before tuning | e.g. `anthropic/...` |  | / 18 |  |  |  |
| 2 — cloud, after tuning  | same |  | / 18 |  |  |  |
| 3 — local               | e.g. `qwen2.5:7b` |  | / 18 |  |  |  |

## What I changed between Run 1 and Run 2

- (the fall in Run 1 was … → I changed …)

## Cloud vs local

- Cloud lasted **N** in a row; local lasted **M**.
- Where local fell short: …
- Notable differences (speed, cost, quality): …

## Per-task detail

Paste the tables from each `run-<provider>-<timestamp>.md` here, or attach the
files. The `.jsonl` next to each is the machine-readable version.

### Run 1 (cloud, before tuning)

```
<paste run-*.md table>
```

### Run 2 (cloud, after tuning)

```
<paste>
```

### Run 3 (local)

```
<paste>
```
