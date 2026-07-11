"""
Local↔cloud RAG comparison.

The Week-7 task: with the local index and *local* retrieval fixed for both sides,
run the same control questions through the **local** chat model and the **cloud**
chat model and rate them on the three axes the mentor asked for:

- **quality**  — deterministic expectation coverage + citation of an expected
                 source, plus a *meaning-match* verdict from a single FIXED judge
                 (the same judge model scores both sides, so neither judges itself).
- **speed**    — wall-clock latency per grounded answer (mean / median / max).
- **stability**— consistency across repeats: latency spread (coefficient of
                 variation), answer-coverage spread within a question, judge-verdict
                 flips, and the error/timeout rate.

Retrieval is identical for both providers: same index, same local embeddings, and
`rag_rewrite` is forced off so the query (hence the retrieved chunks) can't differ
between runs. Only generation changes. Everything routes through the agent's normal
gateway, toggled per run via `config.set("provider", …)`; the judge uses its own
pinned gateway so it is unaffected by the toggle.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .evaluation import ControlQuestion, _cites, _coverage, _split_answer
from .judge import judge_supported


@dataclass
class AnswerSample:
    """One grounded answer for one (provider, question, repeat)."""
    latency_ms: float
    coverage: float
    cited: bool
    grounded: bool
    idk: bool
    quote_match: bool
    error: str | None = None


@dataclass
class Profile:
    """A named configuration to benchmark: an engine + optional config overrides.

    ``params`` are config keys applied for this profile's run (string values, as
    ``config.set`` takes them) — e.g. ``{"temperature": "0.2", "max_tokens": "512",
    "task_template": "android_interview"}``. This is what makes before/after
    optimisation a first-class comparison, not just local vs cloud.
    """
    label: str
    provider: str
    model: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class ProviderReport:
    provider: str
    model: str
    samples: list[AnswerSample]
    # grouped by question, in ask order, for intra-question consistency
    by_question: list[list[AnswerSample]] = field(default_factory=list)
    label: str | None = None
    # Resource consumption (local models only; None for cloud / when not probed).
    tokens_per_sec: float | None = None
    vram_mb: int | None = None
    ctx: int | None = None

    @property
    def column(self) -> str:
        return self.label or f"{self.provider}/{self.model}"

    # ── sample partitions ──
    @property
    def _ok(self) -> list[AnswerSample]:
        return [s for s in self.samples if s.error is None]

    @property
    def _answered(self) -> list[AnswerSample]:
        """Grounded, non-IDK, non-error — the answers whose quality we rate."""
        return [s for s in self._ok if s.grounded and not s.idk]

    # ── quality ──
    @property
    def coverage_mean(self) -> float:
        return _mean([s.coverage for s in self._answered])

    @property
    def citation_rate(self) -> float:
        return _mean([1.0 if s.cited else 0.0 for s in self._answered])

    @property
    def match_rate(self) -> float:
        return _mean([1.0 if s.quote_match else 0.0 for s in self._answered])

    @property
    def idk_rate(self) -> float:
        return _mean([1.0 if s.idk else 0.0 for s in self._ok])

    # ── speed (ms) ──
    @property
    def latency_mean(self) -> float:
        return _mean([s.latency_ms for s in self._ok])

    @property
    def latency_p50(self) -> float:
        lat = [s.latency_ms for s in self._ok]
        return statistics.median(lat) if lat else 0.0

    @property
    def latency_max(self) -> float:
        lat = [s.latency_ms for s in self._ok]
        return max(lat) if lat else 0.0

    # ── stability ──
    @property
    def latency_cv(self) -> float:
        """Coefficient of variation of latency — spread relative to the mean.
        Lower = steadier response times."""
        lat = [s.latency_ms for s in self._ok]
        if len(lat) < 2 or _mean(lat) == 0:
            return 0.0
        return statistics.pstdev(lat) / _mean(lat)

    @property
    def coverage_spread(self) -> float:
        """Mean within-question std-dev of coverage across repeats — how much the
        same question's answer quality wobbles run to run. Lower = steadier."""
        spreads = []
        for group in self.by_question:
            cov = [s.coverage for s in group if s.error is None and not s.idk]
            if len(cov) >= 2:
                spreads.append(statistics.pstdev(cov))
        return _mean(spreads)

    @property
    def verdict_flip_rate(self) -> float:
        """Fraction of questions whose judge verdict was NOT unanimous across
        repeats — a direct read on answer stability."""
        flips = considered = 0
        for group in self.by_question:
            verdicts = [s.quote_match for s in group if s.error is None and not s.idk]
            if len(verdicts) >= 2:
                considered += 1
                if any(verdicts) and not all(verdicts):
                    flips += 1
        return flips / considered if considered else 0.0

    @property
    def error_rate(self) -> float:
        return _mean([1.0 if s.error else 0.0 for s in self.samples])


@dataclass
class CompareReport:
    index_name: str
    k: int
    repeats: int
    n_questions: int
    judge_desc: str
    retrieval_hit_rate: float
    providers: list[ProviderReport]


def compare_configs(
    agent: Any,
    config: Any,
    questions: list[ControlQuestion],
    index_name: str,
    *,
    profiles: list[Profile],
    judge_gateway: Any,
    judge_model: str | None,
    repeats: int = 3,
    k: int = 4,
    probe_resources: bool = False,
    ollama_url: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> CompareReport:
    """Run ``questions`` through each named ``profile`` and score all three axes.

    Each profile applies its own config overrides (params, task_template) on top of
    a fair, shared retrieval base (same local index, no query rewrite), so this
    powers both local-vs-cloud AND before-vs-after-optimisation comparisons. The
    agent's config is snapshotted and restored, so the caller's settings survive.

    ``probe_resources`` additionally measures tokens/sec and VRAM for local profiles
    (a small extra generation + an ``/api/ps`` read); off by default so hermetic
    callers make no network calls.
    """
    saved = config.snapshot()
    reports: list[ProviderReport] = []
    hit_rate = 0.0
    try:
        # Fair, identical retrieval for every profile: local index, no LLM rewrite.
        config.set("rag_rewrite", "off")
        config.set("rag_cite", "on")
        config.set("rag_index", index_name)
        base = config.snapshot()

        # Retrieval, once (independent of the chat provider).
        hits = 0
        for q in questions:
            raw, _enhanced, error = agent.rag_retrieve(q.question, index_name, k)
            if error is None and _retrieval_hit(q, raw):
                hits += 1
        hit_rate = hits / len(questions) if questions else 0.0

        for prof in profiles:
            config.restore(base)          # reset overrides between profiles
            config.set("provider", prof.provider)
            config.set("model", prof.model)
            for key, value in prof.params.items():
                config.set(key, value)

            by_question: list[list[AnswerSample]] = []
            flat: list[AnswerSample] = []
            for qi, q in enumerate(questions):
                group: list[AnswerSample] = []
                for r in range(repeats):
                    if on_progress:
                        on_progress(f"{prof.label}: q{qi+1}/{len(questions)} "
                                    f"repeat {r+1}/{repeats}")
                    group.append(_run_one(agent, q, index_name, k, judge_gateway, judge_model))
                by_question.append(group)
                flat.extend(group)

            report = ProviderReport(prof.provider, prof.model, flat, by_question, label=prof.label)
            if probe_resources and prof.provider == "ollama":
                report.tokens_per_sec, report.vram_mb, report.ctx = _probe_local(
                    prof.model, ollama_url
                )
            reports.append(report)
    finally:
        config.restore(saved)

    return CompareReport(
        index_name=index_name,
        k=k,
        repeats=repeats,
        n_questions=len(questions),
        judge_desc=f"{judge_model or '(engine default)'}",
        retrieval_hit_rate=hit_rate,
        providers=reports,
    )


def compare_providers(
    agent: Any,
    config: Any,
    questions: list[ControlQuestion],
    index_name: str,
    *,
    providers: list[tuple[str, str]],
    judge_gateway: Any,
    judge_model: str | None,
    repeats: int = 3,
    k: int = 4,
    on_progress: Callable[[str], None] | None = None,
) -> CompareReport:
    """Backward-compatible wrapper: compare a list of ``(provider, model)`` pairs
    with no per-profile overrides. See ``compare_configs`` for the general form."""
    profiles = [Profile(f"{p}/{m}", p, m) for p, m in providers]
    return compare_configs(
        agent, config, questions, index_name,
        profiles=profiles, judge_gateway=judge_gateway, judge_model=judge_model,
        repeats=repeats, k=k, on_progress=on_progress,
    )


def _probe_local(model: str, url: str | None) -> tuple[float | None, int | None, int | None]:
    """Measure (tokens/sec, VRAM MB, context window) for a local Ollama model.

    tokens/sec comes from a short native generation (``eval_count`` /
    ``eval_duration``); VRAM and context from ``/api/ps``. Best-effort — any failure
    yields Nones so a probe never breaks the benchmark.
    """
    import requests
    base = (url or "http://localhost:11434").rstrip("/")
    tps = vram_mb = ctx = None
    try:
        r = requests.post(f"{base}/api/generate", json={
            "model": model,
            "prompt": "Explain structured concurrency in two sentences.",
            "stream": False,
        }, timeout=120)
        if r.status_code == 200:
            d = r.json()
            n, dur = d.get("eval_count"), d.get("eval_duration")  # count, nanoseconds
            if n and dur:
                tps = n / (dur / 1e9)
    except requests.RequestException:
        pass
    try:
        r = requests.get(f"{base}/api/ps", timeout=10)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                if m.get("name", "").split(":")[0] == model.split(":")[0]:
                    size = m.get("size_vram") or m.get("size")
                    if size:
                        vram_mb = round(size / (1024 * 1024))
                    ctx = (m.get("context_length")
                           or (m.get("details") or {}).get("context_length"))
                    break
    except requests.RequestException:
        pass
    return tps, vram_mb, ctx


def _run_one(
    agent: Any,
    q: ControlQuestion,
    index_name: str,
    k: int,
    judge_gateway: Any,
    judge_model: str | None,
) -> AnswerSample:
    """One grounded answer, timed, scored, and judged by the fixed judge."""
    t0 = time.perf_counter()
    try:
        g = agent.grounded_answer(q.question, index_name=index_name, k=k)
    except Exception as exc:  # noqa: BLE001 — a bad turn is a data point, not a crash
        return AnswerSample(
            latency_ms=(time.perf_counter() - t0) * 1000,
            coverage=0.0, cited=False, grounded=False, idk=False,
            quote_match=False, error=str(exc),
        )
    latency_ms = (time.perf_counter() - t0) * 1000
    text, idk, results = g["text"], g["idk"], g["results"]

    quote_match = False
    if g["grounded"] and not idk and results:
        body, _quotes = _split_answer(text)
        evidence = "\n\n".join(r.get("text", "") for r in results)
        # Judge on a FIXED gateway/model so both providers are scored by the same
        # judge — a local answer is not graded by the local model, and vice-versa.
        quote_match = judge_supported(judge_gateway, body, evidence, model=judge_model)

    return AnswerSample(
        latency_ms=latency_ms,
        coverage=_coverage(q.expectation, text),
        cited=_cites(q.expected_sources, text),
        grounded=bool(g["grounded"]),
        idk=bool(idk),
        quote_match=quote_match,
    )


def _retrieval_hit(q: ControlQuestion, chunks: list[dict]) -> bool:
    if not q.expected_sources:
        return bool(chunks)
    got = {c.get("metadata", {}).get("filename") for c in chunks}
    return any(src in got for src in q.expected_sources)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def format_compare_report(report: CompareReport) -> str:
    sep = "─" * 78

    def pct(x: float) -> str:
        return f"{round(x * 100)}%"

    def ms(x: float) -> str:
        return f"{round(x)}ms"

    lines = [
        f"Local↔cloud RAG comparison   (index '{report.index_name}', k={report.k}, "
        f"{report.n_questions} questions × {report.repeats} repeats)",
        f"Retrieval (shared, local): expected-source hit-rate {pct(report.retrieval_hit_rate)}",
        f"Meaning-match judge (fixed for both): {report.judge_desc}",
        sep,
    ]
    # Column per profile.
    cols = [p.column for p in report.providers]
    width = max([len(c) for c in cols] + [16])

    def row(name: str, vals: list[str]) -> str:
        return f"  {name:<26}" + "".join(f"{v:>{width + 2}}" for v in vals)

    lines.append(row("", cols))
    lines.append("  " + "─" * (26 + (width + 2) * len(cols)))
    lines.append("  QUALITY")
    lines.append(row("  expectation coverage", [pct(p.coverage_mean) for p in report.providers]))
    lines.append(row("  cites expected source", [pct(p.citation_rate) for p in report.providers]))
    lines.append(row("  supported by sources", [pct(p.match_rate) for p in report.providers]))
    lines.append(row("  \"I don't know\" rate", [pct(p.idk_rate) for p in report.providers]))
    lines.append("  SPEED")
    lines.append(row("  latency mean", [ms(p.latency_mean) for p in report.providers]))
    lines.append(row("  latency median", [ms(p.latency_p50) for p in report.providers]))
    lines.append(row("  latency max", [ms(p.latency_max) for p in report.providers]))
    lines.append("  STABILITY")
    lines.append(row("  latency spread (CV)", [f"{p.latency_cv:.2f}" for p in report.providers]))
    lines.append(row("  coverage spread", [f"{p.coverage_spread:.2f}" for p in report.providers]))
    lines.append(row("  judge-verdict flips", [pct(p.verdict_flip_rate) for p in report.providers]))
    lines.append(row("  error rate", [pct(p.error_rate) for p in report.providers]))

    # RESOURCES — only when at least one profile was probed (local models).
    if any(p.tokens_per_sec is not None or p.vram_mb is not None for p in report.providers):
        def res(v, suffix=""):
            return "—" if v is None else f"{round(v)}{suffix}"
        lines.append("  RESOURCES (local)")
        lines.append(row("  throughput tok/s", [res(p.tokens_per_sec) for p in report.providers]))
        lines.append(row("  VRAM footprint", [res(p.vram_mb, "MB") for p in report.providers]))
        lines.append(row("  context window", [res(p.ctx) for p in report.providers]))
    lines.append(sep)
    lines.append("Lower is better: latency, latency spread (CV), coverage spread, "
                 "verdict flips, error rate. Higher is better: everything under QUALITY.")
    return "\n".join(lines)
