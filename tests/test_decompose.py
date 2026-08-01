"""Day-9 decomposition: the strict parsers and both inference paths, offline.

The LLMEngine seam lets the whole A/B run without a network — FakeEngine returns
scripted stage replies, and every parser is a pure function.
"""

import json

from tests.fake_engine import FakeEngine

from decompose.monolithic import run_monolithic
from decompose.pipeline import run_multistage
from decompose.stages import (
    ACTIONS, Features, parse_features, parse_label, render_features,
)


# ── strict parsers ───────────────────────────────────────────────────────────

def test_parse_features_accepts_a_valid_object():
    f = parse_features('{"sender":"person","action_required":"yes","deadline":"today","importance":"high"}')
    assert f == Features("person", True, "today", "high")


def test_parse_features_tolerates_a_code_fence_and_bool_action():
    f = parse_features('```json\n{"sender":"automated","action_required":false,'
                       '"deadline":"none","importance":"low"}\n```')
    assert f == Features("automated", False, "none", "low")


def test_parse_features_rejects_an_out_of_enum_value():
    assert parse_features('{"sender":"robot","action_required":"yes","deadline":"today","importance":"high"}') is None


def test_parse_features_rejects_a_missing_field():
    assert parse_features('{"sender":"person","deadline":"today","importance":"high"}') is None


def test_parse_label_is_strict_but_tolerates_stray_words():
    assert parse_label("today") == "today"
    assert parse_label("Label: urgent_now") == "urgent_now"
    assert parse_label("someday") is None


def test_render_features_is_compact_key_value():
    text = render_features(Features("person", True, "now", "high"))
    assert text == "sender: person\naction_required: yes\ndeadline: now\nimportance: high"


# ── Option A: monolithic ─────────────────────────────────────────────────────

def test_monolithic_parses_label_and_derives_action_from_the_table():
    reply = json.dumps({"sender": "person", "action_required": "yes", "deadline": "now",
                        "importance": "high", "label": "urgent_now", "action": "whatever",
                        "why": "boss needs it now"})
    engine = FakeEngine(scripted=[reply])
    out = run_monolithic(engine, "m", "Topic: x\nFrom: boss\n\nnow", 0.0)
    assert out.label == "urgent_now"
    assert out.action == ACTIONS["urgent_now"]  # fixed table wins over the model's "action"
    assert out.n_calls == 1
    assert len(engine.calls) == 1


def test_monolithic_malformed_reply_yields_no_label():
    engine = FakeEngine(scripted=["not json at all"])
    out = run_monolithic(engine, "m", "msg", 0.0)
    assert out.label is None
    assert out.action is None


# ── Option B: multi-stage ────────────────────────────────────────────────────

def _models():
    return {"analyze": "small", "decide": "big", "generate": "small"}


def test_multistage_runs_three_stages_and_assembles_the_result():
    scripted = [
        json.dumps({"sender": "person", "action_required": "yes", "deadline": "today", "importance": "high"}),
        "today",
        "It needs a reply today.",
    ]
    engine = FakeEngine(scripted=scripted)
    out = run_multistage(engine, _models(), "Topic: x\nFrom: y\n\nreply today", 0.0)
    assert out.label == "today"
    assert out.action == ACTIONS["today"]
    assert out.why == "It needs a reply today."
    assert out.n_calls == 3


def test_multistage_uses_the_decide_model_for_stage_two_only():
    scripted = [
        json.dumps({"sender": "person", "action_required": "yes", "deadline": "today", "importance": "high"}),
        "today",
        "reason",
    ]
    engine = FakeEngine(scripted=scripted)
    run_multistage(engine, _models(), "msg", 0.0)
    models_used = [params["model"] for _, params in engine.calls]
    assert models_used == ["small", "big", "small"]  # analyze, decide, generate


def test_multistage_short_circuits_on_a_bad_analysis():
    # Stage 1 emits an out-of-enum value → parse fails → stop after one call.
    engine = FakeEngine(scripted=['{"sender":"alien","action_required":"yes","deadline":"now","importance":"high"}',
                                  "today", "reason"])
    out = run_multistage(engine, _models(), "msg", 0.0)
    assert out.label is None
    assert out.features is None
    assert out.n_calls == 1
    assert len(engine.calls) == 1  # stages 2 and 3 never ran


def test_tuned_decide_classifies_the_message_not_the_features():
    from finetune.common import SYSTEM_PROMPT
    scripted = [
        json.dumps({"sender": "person", "action_required": "yes", "deadline": "now", "importance": "high"}),
        "urgent_now",           # the tuned classifier's label, from the raw message
        "The boss needs it now.",
    ]
    engine = FakeEngine(scripted=scripted)
    msg = "Topic: deck\nFrom: boss\n\nneed it now"
    out = run_multistage(engine, _models(), msg, 0.0, tuned_decide="jarvis-classifier")
    assert out.label == "urgent_now"
    assert out.n_calls == 3
    # Stage 2 used the tuned model, the classifier system prompt, and the raw message.
    sys2, user2 = engine.calls[1][0][0]["content"], engine.calls[1][0][1]["content"]
    assert engine.calls[1][1]["model"] == "jarvis-classifier"
    assert sys2 == SYSTEM_PROMPT
    assert user2 == msg  # the message, not rendered features


def test_multistage_short_circuits_on_a_bad_decision():
    scripted = [
        json.dumps({"sender": "person", "action_required": "no", "deadline": "none", "importance": "low"}),
        "not_a_label",
    ]
    engine = FakeEngine(scripted=scripted)
    out = run_multistage(engine, _models(), "msg", 0.0)
    assert out.label is None
    assert out.features is not None  # analysis survived; only the decision failed
    assert out.n_calls == 2
