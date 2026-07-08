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
class ProviderReport:
    provider: str
    model: str
    samples: list[AnswerSample]
    # grouped by question, in ask order, for intra-question consistency
    by_question: list[list[AnswerSample]] = field(default_factory=list)

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
    """Run ``questions`` through each (provider, model) in ``providers`` and score.

    ``providers`` is a list of ``(provider, model)`` pairs, e.g.
    ``[("ollama", "qwen2.5:7b"), ("openrouter", "google/gemini-2.5-flash")]``.
    Retrieval is measured once (shared, local). The agent's config is snapshotted
    and restored, so the caller's settings are untouched afterwards.
    """
    saved = config.snapshot()
    reports: list[ProviderReport] = []
    hit_rate = 0.0
    try:
        # Fair, identical retrieval for both sides: local index, no LLM query rewrite.
        config.set("rag_rewrite", "off")
        config.set("rag_cite", "on")
        config.set("rag_index", index_name)

        # Retrieval, once (independent of the chat provider).
        hits = 0
        for q in questions:
            raw, _enhanced, error = agent.rag_retrieve(q.question, index_name, k)
            if error is None and _retrieval_hit(q, raw):
                hits += 1
        hit_rate = hits / len(questions) if questions else 0.0

        for provider, model in providers:
            config.set("provider", provider)
            config.set("model", model)
            by_question: list[list[AnswerSample]] = []
            flat: list[AnswerSample] = []
            for q in questions:
                group: list[AnswerSample] = []
                for r in range(repeats):
                    if on_progress:
                        on_progress(f"{provider}: q{questions.index(q)+1}/{len(questions)} "
                                    f"repeat {r+1}/{repeats}")
                    group.append(_run_one(agent, q, index_name, k, judge_gateway, judge_model))
                by_question.append(group)
                flat.extend(group)
            reports.append(ProviderReport(provider, model, flat, by_question))
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
    # Column per provider.
    cols = [f"{p.provider}/{p.model}" for p in report.providers]
    width = max([len(c) for c in cols] + [22])

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
    lines.append(sep)
    lines.append("Lower is better: latency, latency spread (CV), coverage spread, "
                 "verdict flips, error rate. Higher is better: everything under QUALITY.")
    return "\n".join(lines)
