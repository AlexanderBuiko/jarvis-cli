"""Model escalation router: the decide() policy and route() orchestration, offline.

The LLMEngine seam lets the whole routing rule run without a network — FakeEngine
returns scripted JSON, and decide() is a pure function of one answer.
"""

import json

from jarvis.openrouter.client import Completion
from tests.fake_engine import FakeEngine

from confidence.classify import ScoredRun

from routing.answer import AnswerRun, _parse
from routing.classify_run import _should_escalate
from routing.heuristics import is_hedged, word_count
from routing.router import Config, Tiers, decide, route
from routing.runtime import Tier


def _run(answer, confidence, error=None):
    completion = Completion(text="", finish_reason="stop", request={}, response={}, latency_ms=0.0)
    return AnswerRun(answer=answer, confidence=confidence, text="", completion=completion, error=error)


# ── decide(): the pure escalation policy ─────────────────────────────────────

def test_high_confidence_plain_answer_stays_on_cheap():
    decision = decide(_run("Paris.", 0.98), Config())
    assert decision.escalate is False
    assert decision.reasons == []


def test_low_confidence_escalates():
    decision = decide(_run("Maybe around 40?", 0.2), Config())
    assert decision.escalate is True
    assert decision.reasons and decision.reasons[0].startswith("low_confidence")


def test_short_high_confidence_answer_is_not_escalated_by_length():
    # "2+2" -> "4" is short but certain; length must not fire above conf_high.
    decision = decide(_run("4", 0.99), Config())
    assert decision.escalate is False


def test_middle_band_plus_hedge_escalates():
    decision = decide(_run("I'm not sure, it depends on the context.", 0.6), Config())
    assert decision.escalate is True
    assert "hedged" in decision.reasons


def test_middle_band_short_answer_corroborates_escalation():
    decision = decide(_run("Probably.", 0.6), Config(min_words=4))
    assert decision.escalate is True
    assert "too_short" in decision.reasons


def test_middle_band_confident_enough_and_long_stays():
    decision = decide(_run("The boiling point is one hundred degrees Celsius at sea level.", 0.6),
                      Config())
    assert decision.escalate is False


def test_high_confidence_but_hedged_text_escalates_on_contradiction():
    decision = decide(_run("Honestly I'm not sure but here is a guess.", 0.9), Config())
    assert decision.escalate is True
    assert "hedged_despite_high_confidence" in decision.reasons


def test_missing_confidence_escalates():
    decision = decide(_run("Some answer with several words here.", None), Config())
    assert decision.escalate is True
    assert "no_confidence" in decision.reasons


def test_unparseable_cheap_answer_escalates():
    decision = decide(_run(None, None), Config())
    assert decision.escalate is True
    assert "cheap_unparseable" in decision.reasons


def test_cheap_provider_error_escalates():
    decision = decide(_run(None, None, error="Provider returned error 400"), Config())
    assert decision.escalate is True
    assert "cheap_error" in decision.reasons


# ── route(): orchestration and the fallback call count ───────────────────────

def _tiers(cheap_engine, strong_engine):
    return Tiers(cheap=Tier("cheap", cheap_engine, "small"),
                 strong=Tier("strong", strong_engine, "big"))


def test_confident_cheap_answer_spends_one_call_and_is_served():
    cheap = FakeEngine(scripted=[json.dumps({"answer": "Paris.", "confidence": 0.97})])
    strong = FakeEngine(scripted=[json.dumps({"answer": "should not be used", "confidence": 0.9})])
    result = route(_tiers(cheap, strong), "What is the capital of France?")
    assert result.escalated is False
    assert result.served_by == "cheap"
    assert result.final_answer == "Paris."
    assert result.n_calls == 1
    assert len(cheap.calls) == 1
    assert len(strong.calls) == 0  # strong tier never touched on a confident answer


def test_uncertain_cheap_answer_escalates_and_serves_strong():
    cheap = FakeEngine(scripted=[json.dumps({"answer": "I'm not sure.", "confidence": 0.2})])
    strong = FakeEngine(scripted=[json.dumps({"answer": "The ball costs $0.05.", "confidence": 0.95})])
    result = route(_tiers(cheap, strong), "bat and ball problem")
    assert result.escalated is True
    assert result.served_by == "strong"
    assert result.final_answer == "The ball costs $0.05."
    assert result.cheap_answer == "I'm not sure."
    assert result.n_calls == 2
    assert len(strong.calls) == 1


def test_cheap_provider_failure_falls_back_to_strong_without_crashing():
    def boom(messages, params):
        raise RuntimeError("Ollama not reachable")

    cheap = FakeEngine(responder=boom)
    strong = FakeEngine(scripted=[json.dumps({"answer": "A solid answer.", "confidence": 0.9})])
    result = route(_tiers(cheap, strong), "anything")
    assert result.escalated is True
    assert "cheap_error" in result.reasons
    assert result.final_answer == "A solid answer."
    assert result.n_calls == 2


# ── the primitive parser and length signals ──────────────────────────────────

def test_parse_tolerates_a_code_fence_and_stray_text():
    ans, conf = _parse('sure:\n```json\n{"answer": "42", "confidence": 0.8}\n```')
    assert ans == "42"
    assert conf == 0.8


def test_parse_rejects_empty_answer_string():
    ans, conf = _parse('{"answer": "   ", "confidence": 0.9}')
    assert ans is None
    assert conf == 0.9


def test_length_and_hedge_signals():
    assert word_count("one two three") == 3
    assert is_hedged("Well, it depends.") is True
    assert is_hedged("The capital is Paris.") is False


# ── classification routing gate (confidence-only) ────────────────────────────

def _scored(label, confidence, error=None):
    completion = Completion(text="", finish_reason="stop", request={}, response={}, latency_ms=0.0)
    return ScoredRun(label=label, confidence=confidence, text="", completion=completion, error=error)


def test_confident_label_stays_on_cheap():
    escalate, reason = _should_escalate(_scored("today", 0.95), conf_low=0.6)
    assert escalate is False
    assert reason == ""


def test_low_confidence_label_escalates():
    escalate, reason = _should_escalate(_scored("today", 0.3), conf_low=0.6)
    assert escalate is True
    assert reason.startswith("low_confidence")


def test_unparseable_label_escalates():
    escalate, reason = _should_escalate(_scored(None, None), conf_low=0.6)
    assert escalate is True
    assert reason == "cheap_unparseable"


def test_errored_cheap_label_escalates():
    escalate, reason = _should_escalate(_scored(None, None, error="filtered"), conf_low=0.6)
    assert escalate is True
    assert reason == "cheap_error"
