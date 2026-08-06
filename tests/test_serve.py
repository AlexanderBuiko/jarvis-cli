"""LLM core server — the ``handle_complete`` contract, faked at the ``complete_fn`` seam."""

from jarvis.serve.server import LLMCore


def _fake_complete(text="hi", **fields):
    body = {"text": text, "model": "fake-1", "prompt_tokens": 5,
            "completion_tokens": 2, "cost_usd": 0.0, "latency_ms": 11.0}
    body.update(fields)
    return lambda system, user, *, provider, model: body


def test_completes_and_returns_the_metered_body():
    core = LLMCore(complete_fn=_fake_complete())
    status, body = core.handle_complete({"user": "2 rooms", "provider": "ollama"})
    assert status == 200
    assert body["text"] == "hi"
    assert body["model"] == "fake-1"
    assert body["cost_usd"] == 0.0


def test_missing_user_is_rejected_before_the_provider():
    called: list[bool] = []

    def spy(system, user, *, provider, model):
        called.append(True)
        return {}

    core = LLMCore(complete_fn=spy)
    status, body = core.handle_complete({"system": "x"})
    assert status == 400
    assert "user" in body["error"]
    assert called == []          # never reached the provider


def test_provider_failure_degrades_to_502_not_a_crash():
    def boom(system, user, *, provider, model):
        raise RuntimeError("ollama down")

    core = LLMCore(complete_fn=boom)
    status, body = core.handle_complete({"user": "hi"})
    assert status == 502
    assert "provider call failed" in body["error"]


def test_deploy_can_pin_the_model_via_env(monkeypatch):
    seen: dict = {}

    def spy(system, user, *, provider, model):
        seen["model"] = model
        return {"text": "ok"}

    core = LLMCore(complete_fn=spy)
    monkeypatch.setenv("JARVIS_LLM_MODEL", "meta-llama/llama-3.3-70b-instruct")
    core.handle_complete({"user": "hi"})               # body names no model -> env pins it
    assert seen["model"] == "meta-llama/llama-3.3-70b-instruct"
    core.handle_complete({"user": "hi", "model": "google/gemini-2.5-flash"})
    assert seen["model"] == "google/gemini-2.5-flash"  # explicit per-request still wins


def test_provider_defaults_when_body_omits_it():
    seen: dict = {}

    def spy(system, user, *, provider, model):
        seen["provider"] = provider
        return {"text": "ok"}

    core = LLMCore(default_provider="openrouter", complete_fn=spy)
    core.handle_complete({"user": "hi"})
    assert seen["provider"] == "openrouter"
