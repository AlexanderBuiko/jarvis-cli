"""
RAG application layer — using a built index to answer questions.

The retrieval substrate lives in ``jarvis.indexing``; the *generation* side (the
with/without-RAG comparison and the control-question evaluation) lives here. The
agent exposes the two-mode primitives (``answer`` / ``compare_rag`` /
``rag_search``); this package adds the evaluation harness on top.
"""

from .evaluation import (
    ControlQuestion,
    QuestionResult,
    EvalReport,
    load_questions,
    evaluate,
    format_report,
    DEFAULT_QUESTIONS_PATH,
)

__all__ = [
    "ControlQuestion",
    "QuestionResult",
    "EvalReport",
    "load_questions",
    "evaluate",
    "format_report",
    "DEFAULT_QUESTIONS_PATH",
]
