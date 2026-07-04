"""
Control-question evaluation for RAG quality.

Runs a small fixed set of questions and scores, all deterministically (no LLM
judge, so it is cheap and testable):

1. **Retrieval hit** — did the first-stage top-K include an expected source?
   (the lecture's "were the right chunks found?")
2. **Retrieval precision, before vs after the second stage** — the fraction of
   kept chunks that come from an expected source, measured on the raw top-K and
   again after the filter/rerank. This is the with/without-filter comparison, and
   it needs no chat calls.
3. **Expectation coverage** (optional, ``generate_answers``) — how much of each
   answer's expected key phrases are present, without RAG vs with (enhanced) RAG.
4. **Citation** — does the grounded answer name an expected source?

Each question is a `ControlQuestion`:

    { "question": "...", "expectation": ["key phrase", ...],
      "expected_sources": ["filename.md", ...] }

Retrieval scoring is always done (free). Answer generation (``generate_answers``)
adds ~2 chat calls per question.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Overlap bar above which an answer is judged to "match" its quotes.
_MATCH_BAR = 0.3
_MATCH_STOPWORDS = frozenset(
    "the a an of to in on for and or is are how do you it with as at be this that your "
    "can when what which from by not have will would should more also than then".split()
)

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
    retrieved_before: list[str]
    retrieved_after: list[str]
    retrieval_hit: bool          # expected source in the first-stage top-K
    retained_after: bool         # expected source still present after filter/rerank
    precision_before: float      # fraction of top-K chunks from an expected source
    precision_after: float       # same, after the second stage
    plain_coverage: float
    rag_coverage: float
    cited_expected: bool
    has_sources: bool = False    # the RAG answer includes a Sources: list
    has_quotes: bool = False     # the RAG answer includes Quotes:
    quote_overlap: float = 0.0   # answer↔quotes lexical overlap (meaning-match proxy)
    quote_match: bool = False    # overlap above the match bar
    is_idk: bool = False         # answered "I don't know" (strict weak context)
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
    def retention_rate(self) -> float:
        return _mean([1.0 if r.retained_after else 0.0 for r in self.results])

    @property
    def avg_precision_before(self) -> float:
        return _mean([r.precision_before for r in self.results])

    @property
    def avg_precision_after(self) -> float:
        return _mean([r.precision_after for r in self.results])

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

    @property
    def _grounded(self) -> list[QuestionResult]:
        """Answered ones that actually grounded (exclude IDK / errors)."""
        return [r for r in self.results if r.rag_answer and not r.is_idk]

    @property
    def sources_rate(self) -> float:
        g = self._grounded
        return _mean([1.0 if r.has_sources else 0.0 for r in g]) if g else 0.0

    @property
    def quotes_rate(self) -> float:
        g = self._grounded
        return _mean([1.0 if r.has_quotes else 0.0 for r in g]) if g else 0.0

    @property
    def match_rate(self) -> float:
        g = self._grounded
        return _mean([1.0 if r.quote_match else 0.0 for r in g]) if g else 0.0

    @property
    def idk_count(self) -> int:
        return sum(1 for r in self.results if r.is_idk)


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
    """Score each question's retrieval (before/after the second stage) and,
    optionally, both answers.

    ``agent`` must expose ``rag_retrieve`` and ``answer`` (JarvisAgent does). The
    second-stage settings (min_score / top_n / rerank / rewrite) come from the
    agent's active config, so callers compare by toggling those.
    """
    results: list[QuestionResult] = []
    for q in questions:
        raw, enhanced, error = agent.rag_retrieve(q.question, index_name, k)
        before = _unique_sources(raw)
        after = _unique_sources(enhanced)

        plain, grounded, is_idk = "", None, False
        if generate_answers:
            plain = agent.answer(q.question)
            if error is None:
                g = agent.grounded_answer(q.question, index_name, k)
                grounded, is_idk = g["text"], g["idk"]

        rag_text = grounded or ""
        overlap = _quote_overlap(rag_text)
        results.append(QuestionResult(
            question=q.question,
            expected_sources=q.expected_sources,
            retrieved_before=before,
            retrieved_after=after,
            retrieval_hit=_hit(q.expected_sources, before, raw),
            retained_after=_hit(q.expected_sources, after, enhanced),
            precision_before=_precision(raw, q.expected_sources),
            precision_after=_precision(enhanced, q.expected_sources),
            plain_coverage=_coverage(q.expectation, plain),
            rag_coverage=_coverage(q.expectation, rag_text),
            cited_expected=_cites(q.expected_sources, rag_text),
            has_sources=("Sources:" in rag_text),
            has_quotes=("Quotes:" in rag_text),
            quote_overlap=overlap,
            quote_match=(overlap >= _MATCH_BAR),
            is_idk=is_idk,
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
        f"  {'#':>2}  {'hit':>3}  {'prec→':>11}  {'rag':>5}  {'src':>3}  {'quo':>3}  {'mat':>3}  question",
        f"  {'──':>2}  {'───':>3}  {'───────────':>11}  {'───':>5}  {'───':>3}  {'───':>3}  {'───':>3}  ────────",
    ]
    mark = lambda b: "✓" if b else "·"
    for i, r in enumerate(report.results, 1):
        hit = "✓" if r.retrieval_hit else "✗"
        prec = f"{pct(r.precision_before)}→{pct(r.precision_after)}"
        q = r.question if len(r.question) <= 38 else r.question[:37] + "…"
        if report.answers_generated:
            rag = "IDK" if r.is_idk else pct(r.rag_coverage)
            lines.append(
                f"  {i:>2}  {hit:>3}  {prec:>11}  {rag:>5}  {mark(r.has_sources):>3}  "
                f"{mark(r.has_quotes):>3}  {mark(r.quote_match):>3}  {q}"
            )
        else:
            lines.append(f"  {i:>2}  {hit:>3}  {prec:>11}  {'—':>5}  {'—':>3}  {'—':>3}  {'—':>3}  {q}")
        if r.error:
            lines.append(f"        ! {r.error}")
    lines += ["", sep, "Summary", sep,
              f"  Retrieval hit-rate (expected source in top-K): {pct(report.retrieval_hit_rate)}",
              f"  Retrieval precision — before second stage:     {pct(report.avg_precision_before)}",
              f"  Retrieval precision — after filter/rerank:     {pct(report.avg_precision_after)}",
              f"  Expected source retained after filtering:      {pct(report.retention_rate)}"]
    if report.answers_generated:
        lines += [
            f"  Avg expectation coverage — without RAG: {pct(report.avg_plain_coverage)}",
            f"  Avg expectation coverage — with RAG:    {pct(report.avg_rag_coverage)}",
            f"  Answers citing an expected source:      {pct(report.citation_rate)}",
            f"  Questions improved by RAG:              {report.improved}/{report.n}",
            "",
            "  Mandatory-citations checks (over grounded answers):",
            f"  · Answers with a Sources list:          {pct(report.sources_rate)}",
            f"  · Answers with Quotes:                  {pct(report.quotes_rate)}",
            f"  · Answer meaning matches its quotes:    {pct(report.match_rate)}",
            f"  · 'I don't know' (weak context):        {report.idk_count}/{report.n}",
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


def _hit(expected: list[str], retrieved: list[str], chunks: list[dict]) -> bool:
    """Was an expected source retrieved? With no expectation, any chunk counts."""
    if not expected:
        return bool(chunks)
    return any(src in retrieved for src in expected)


def _quote_overlap(rag_text: str) -> float:
    """Lexical overlap between the answer body and its Quotes block — a proxy for
    'does the answer's meaning match the quotes'. Fraction of the answer's
    significant words that also appear in the quoted fragments."""
    if "Quotes:" not in rag_text:
        return 0.0
    body = rag_text.split("\nSources:", 1)[0]
    quotes = rag_text.split("Quotes:", 1)[1]
    answer_words = _sig_words(body)
    quote_words = _sig_words(quotes)
    if not answer_words:
        return 0.0
    return len(answer_words & quote_words) / len(answer_words)


def _sig_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z_]+", text.lower())
            if len(w) > 3 and w not in _MATCH_STOPWORDS}


def _precision(chunks: list[dict], expected: list[str]) -> float:
    """Fraction of retrieved chunks that come from an expected source."""
    if not chunks or not expected:
        return 0.0
    good = sum(1 for c in chunks if c.get("metadata", {}).get("filename") in expected)
    return good / len(chunks)


def _unique_sources(chunks: list[dict]) -> list[str]:
    out: list[str] = []
    for c in chunks:
        fn = c.get("metadata", {}).get("filename", "?")
        if fn not in out:
            out.append(fn)
    return out


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
