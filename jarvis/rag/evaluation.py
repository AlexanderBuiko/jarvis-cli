"""
Control-question evaluation for RAG quality.

Runs a small fixed set of questions through the agent **both ways** (without RAG
and with RAG) and scores three things, all deterministically (no LLM judge, so it
is cheap and testable):

1. **Retrieval hit** — did the retrieved chunks include an expected source file?
   (objective, index-only; the lecture's "were the right chunks found?")
2. **Expectation coverage** — what fraction of the expected key phrases appear in
   each answer? Compared between the two modes (the "is the final answer right?").
3. **Citation** — does the grounded answer name an expected source?

Each question is a `ControlQuestion`:

    { "question": "...", "expectation": ["key phrase", ...],
      "expected_sources": ["filename.md", ...] }

The answer-generation step calls the chat model twice per question (with/without),
so a full run costs ~2N completions — set ``generate_answers=False`` for a cheap
retrieval-only check.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Ships with the repo alongside the default knowledge_base corpus.
DEFAULT_QUESTIONS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "knowledge_base" / "eval" / "questions.json"
)


@dataclass
class ControlQuestion:
    question: str
    expectation: list[str]
    expected_sources: list[str] = field(default_factory=list)


@dataclass
class QuestionResult:
    question: str
    expected_sources: list[str]
    retrieved_sources: list[str]
    retrieval_hit: bool
    plain_coverage: float
    rag_coverage: float
    cited_expected: bool
    plain_answer: str = ""
    rag_answer: str | None = None
    error: str | None = None


@dataclass
class EvalReport:
    results: list[QuestionResult]
    index_name: str
    k: int
    answers_generated: bool

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def retrieval_hit_rate(self) -> float:
        return _mean([1.0 if r.retrieval_hit else 0.0 for r in self.results])

    @property
    def avg_plain_coverage(self) -> float:
        return _mean([r.plain_coverage for r in self.results])

    @property
    def avg_rag_coverage(self) -> float:
        return _mean([r.rag_coverage for r in self.results])

    @property
    def citation_rate(self) -> float:
        return _mean([1.0 if r.cited_expected else 0.0 for r in self.results])

    @property
    def improved(self) -> int:
        """Questions where RAG's expectation coverage beat the plain answer's."""
        return sum(1 for r in self.results if r.rag_coverage > r.plain_coverage)


def load_questions(path: str | Path = DEFAULT_QUESTIONS_PATH) -> list[ControlQuestion]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        ControlQuestion(
            question=item["question"],
            expectation=item.get("expectation", []),
            expected_sources=item.get("expected_sources", []),
        )
        for item in data
    ]


def evaluate(
    agent,
    questions: list[ControlQuestion],
    index_name: str,
    *,
    k: int = 5,
    generate_answers: bool = True,
) -> EvalReport:
    """Score each question's retrieval and (optionally) both answers.

    ``agent`` must expose ``rag_search`` and ``compare_rag`` (JarvisAgent does).
    Retrieval is always scored; answer coverage/citation only when
    ``generate_answers`` is True.
    """
    results: list[QuestionResult] = []
    for q in questions:
        if generate_answers:
            plain, grounded, chunks, error = agent.compare_rag(q.question, index_name, k)
        else:
            plain, grounded, error = "", None, None
            try:
                chunks = agent.rag_search(q.question, index_name, k)
            except Exception as exc:  # noqa: BLE001 — record, keep going
                chunks, error = [], str(exc)

        retrieved = _unique_sources(chunks)
        hit = any(src in retrieved for src in q.expected_sources) if q.expected_sources else bool(chunks)
        results.append(QuestionResult(
            question=q.question,
            expected_sources=q.expected_sources,
            retrieved_sources=retrieved,
            retrieval_hit=hit,
            plain_coverage=_coverage(q.expectation, plain),
            rag_coverage=_coverage(q.expectation, grounded or ""),
            cited_expected=_cites(q.expected_sources, grounded or ""),
            plain_answer=plain,
            rag_answer=grounded,
            error=error,
        ))
    return EvalReport(results, index_name, k, generate_answers)


def format_report(report: EvalReport) -> str:
    sep = "─" * 78
    pct = lambda x: f"{round(x * 100)}%"
    lines = [
        f"RAG control-question evaluation   (index '{report.index_name}', k={report.k}, "
        f"{report.n} questions)", sep,
        f"  {'#':>2}  {'hit':>3}  {'plain':>5}  {'rag':>5}  {'cite':>4}  question",
        f"  {'──':>2}  {'───':>3}  {'─────':>5}  {'───':>5}  {'────':>4}  ────────",
    ]
    for i, r in enumerate(report.results, 1):
        hit = "✓" if r.retrieval_hit else "✗"
        cite = "✓" if r.cited_expected else "·"
        q = r.question if len(r.question) <= 46 else r.question[:45] + "…"
        if report.answers_generated:
            lines.append(
                f"  {i:>2}  {hit:>3}  {pct(r.plain_coverage):>5}  "
                f"{pct(r.rag_coverage):>5}  {cite:>4}  {q}"
            )
        else:
            lines.append(f"  {i:>2}  {hit:>3}  {'—':>5}  {'—':>5}  {'—':>4}  {q}")
        if r.error:
            lines.append(f"        ! {r.error}")
    lines += ["", sep, "Summary", sep,
              f"  Retrieval hit-rate (expected source in top-k): {pct(report.retrieval_hit_rate)}"]
    if report.answers_generated:
        lines += [
            f"  Avg expectation coverage — without RAG: {pct(report.avg_plain_coverage)}",
            f"  Avg expectation coverage — with RAG:    {pct(report.avg_rag_coverage)}",
            f"  Answers citing an expected source:      {pct(report.citation_rate)}",
            f"  Questions improved by RAG:              {report.improved}/{report.n}",
        ]
    else:
        lines.append("  (answer generation skipped — retrieval-only run)")
    lines.append(sep)
    return "\n".join(lines)


# ── Scoring helpers ──────────────────────────────────────────────────────────


def _coverage(expectation: list[str], answer: str) -> float:
    """Fraction of expected key phrases that appear (case-insensitive) in answer."""
    if not expectation:
        return 0.0
    low = answer.lower()
    hits = sum(1 for phrase in expectation if phrase.lower() in low)
    return hits / len(expectation)


def _cites(expected_sources: list[str], answer: str) -> bool:
    """True if the answer names an expected source file (with or without .md)."""
    low = answer.lower()
    for src in expected_sources:
        name = src.lower()
        if name in low or name.rsplit(".", 1)[0] in low:
            return True
    return False


def _unique_sources(chunks: list[dict]) -> list[str]:
    out: list[str] = []
    for c in chunks:
        fn = c.get("metadata", {}).get("filename", "?")
        if fn not in out:
            out.append(fn)
    return out


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
