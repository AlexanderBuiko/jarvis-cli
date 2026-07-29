"""Day-7 confidence layer: the fusion policy and orchestration, driven offline.

The whole point of the LLMEngine seam is that the decision logic is testable
without a network — FakeEngine returns scripted JSON, and fuse() is pure.
"""

import json

from jarvis.openrouter.client import Completion
from tests.fake_engine import FakeEngine

from confidence.assess import Config, assess, fuse
from confidence.classify import ScoredRun, _parse, classify_scored


def _run(label, confidence):
    completion = Completion(text="", finish_reason="stop", request={}, response={}, latency_ms=0.0)
    return ScoredRun(label=label, confidence=confidence, text="", completion=completion)


def test_full_agreement_and_high_confidence_is_ok():
    runs = [_run("today", 0.9), _run("today", 0.85), _run("today", 0.95)]
    verdict, label, agreement, mean_conf = fuse(runs, Config())
    assert verdict == "OK"
    assert label == "today"
    assert agreement == 1.0


def test_split_majority_is_unsure():
    runs = [_run("today", 0.9), _run("today", 0.9), _run("ignore", 0.9)]
    verdict, label, _, _ = fuse(runs, Config())
    assert verdict == "UNSURE"
    assert label == "today"


def test_three_way_disagreement_has_no_majority_and_fails():
    runs = [_run("today", 0.9), _run("ignore", 0.9), _run("this_week", 0.9)]
    verdict, _, _, _ = fuse(runs, Config())
    assert verdict == "FAIL"


def test_all_malformed_replies_fail_the_constraint_gate():
    runs = [_run(None, None), _run(None, None), _run(None, None)]
    verdict, label, _, _ = fuse(runs, Config())
    assert verdict == "FAIL"
    assert label is None


def test_agreement_but_low_confidence_is_rejected():
    runs = [_run("today", 0.2), _run("today", 0.25), _run("today", 0.2)]
    verdict, _, _, mean_conf = fuse(runs, Config())
    assert verdict == "FAIL"
    assert mean_conf < Config().conf_low


def test_assess_spends_exactly_n_calls_and_accepts_a_confident_agreement():
    scripted = [json.dumps({"label": "urgent_now", "confidence": 0.9}) for _ in range(3)]
    engine = FakeEngine(scripted=scripted)
    result = assess(engine, "test/model", "Topic: x\nFrom: y\n\nhello", Config(n=3))
    assert result.n_calls == 3
    assert len(engine.calls) == 3
    assert result.verdict == "OK"
    assert result.accepted is True


def test_unsure_escalates_and_adds_reinference_calls():
    # First round splits 2/1 -> UNSURE; escalation samples 3 more.
    scripted = [
        json.dumps({"label": "today", "confidence": 0.9}),
        json.dumps({"label": "today", "confidence": 0.9}),
        json.dumps({"label": "ignore", "confidence": 0.9}),
    ] + [json.dumps({"label": "today", "confidence": 0.9}) for _ in range(3)]
    engine = FakeEngine(scripted=scripted)
    result = assess(engine, "test/model", "msg", Config(n=3, escalate=True, escalate_n=3))
    assert result.escalated is True
    assert result.n_calls == 6


def test_provider_error_degrades_to_fail_without_crashing():
    # A responder that always raises simulates a content filter / provider 400.
    def boom(messages, params):
        raise RuntimeError("Provider returned error 400")

    engine = FakeEngine(responder=boom)
    result = assess(engine, "test/model", "contradictory input", Config(n=3))
    assert result.verdict == "FAIL"
    assert result.n_errors == 3
    assert result.n_calls == 3  # still counts the attempts; no exception escaped


def test_one_filtered_sample_still_lets_a_majority_stand():
    # 2 good + 1 raising: redundancy tolerates the single failure.
    calls = {"i": 0}

    def responder(messages, params):
        calls["i"] += 1
        if calls["i"] == 2:
            raise RuntimeError("filtered")
        return json.dumps({"label": "urgent_now", "confidence": 0.9})

    engine = FakeEngine(responder=responder)
    result = assess(engine, "test/model", "msg", Config(n=3))
    assert result.n_errors == 1
    assert result.label == "urgent_now"
    # 2/3 agreement -> UNSURE (rejected), but not a crash and not a FAIL
    assert result.verdict == "UNSURE"


def test_parse_tolerates_a_code_fence_and_stray_text():
    label, conf = _parse('here you go:\n```json\n{"label": "ignore", "confidence": 0.4}\n```')
    assert label == "ignore"
    assert conf == 0.4


def test_parse_rejects_an_unknown_label():
    label, conf = _parse('{"label": "someday", "confidence": 0.9}')
    assert label is None
    assert conf == 0.9


def test_classify_scored_sends_seed_and_temperature():
    engine = FakeEngine(scripted=[json.dumps({"label": "today", "confidence": 0.8})])
    run = classify_scored(engine, "test/model", "msg", temperature=0.6, seed=1001)
    assert run.label == "today"
    _, params = engine.calls[0]
    assert params["seed"] == 1001
    assert params["temperature"] == 0.6
