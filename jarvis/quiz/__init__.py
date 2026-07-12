"""Offline quiz-pool generation (the question factory).

Builds a reviewable pool of multiple-choice questions from a local index using the
local model, then hands it off (via ``quiz upload``) to the private Telegram-bot
server. The KB never leaves here — only the generated, transformative MCQs do.
"""

from .builder import MCQ, build_pool, mcqs_to_json, validate_pool

__all__ = ["MCQ", "build_pool", "mcqs_to_json", "validate_pool"]
