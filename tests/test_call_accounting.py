"""Tests for the LLM-call accounting helper (jarvis.llm.accounting).

`make_call_record` computes cost from usage and the engine's pricing. It is
driven here through a small pricing-only fake at the LLMEngine seam, so no
network and no real provider are touched.
"""

import unittest

from jarvis.llm.accounting import make_call_record
from jarvis.openrouter.client import Completion


class _PricingEngine:
    """Minimal LLMEngine stand-in that only answers pricing lookups."""

    def __init__(self, pricing: dict[str, tuple[float | None, float | None]]) -> None:
        self._pricing = pricing

    def get_pricing(self, model_id: str) -> tuple[float | None, float | None]:
        return self._pricing.get(model_id, (None, None))


def _completion(
    request_model: str | None,
    response_model: str | None,
    usage: dict | None,
) -> Completion:
    response: dict = {}
    if response_model is not None:
        response["model"] = response_model
    if usage is not None:
        response["usage"] = usage
    response["id"] = "resp-1"
    return Completion(
        text="hello",
        finish_reason="stop",
        request={"model": request_model} if request_model else {},
        response=response,
        latency_ms=12.5,
    )


class CostComputationTest(unittest.TestCase):
    def test_cost_is_priced_from_usage_and_pricing(self):
        engine = _PricingEngine({"model-x": (10.0, 20.0)})
        completion = _completion(
            "model-x", "model-x",
            {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
        )
        record = make_call_record(3, "planning", completion, engine)
        self.assertAlmostEqual(record["cost"]["input_usd"], 10.0)
        self.assertAlmostEqual(record["cost"]["output_usd"], 10.0)
        self.assertAlmostEqual(record["cost"]["total_usd"], 20.0)

    def test_all_cost_fields_are_none_when_pricing_is_unavailable(self):
        engine = _PricingEngine({})
        completion = _completion(
            "model-x", "model-x",
            {"prompt_tokens": 100, "completion_tokens": 50},
        )
        record = make_call_record(0, "chat", completion, engine)
        self.assertIsNone(record["cost"]["input_usd"])
        self.assertIsNone(record["cost"]["output_usd"])
        self.assertIsNone(record["cost"]["total_usd"])

    def test_cost_is_none_when_usage_is_missing(self):
        engine = _PricingEngine({"model-x": (10.0, 20.0)})
        completion = _completion("model-x", "model-x", None)
        record = make_call_record(0, "chat", completion, engine)
        self.assertIsNone(record["cost"]["input_usd"])
        self.assertIsNone(record["cost"]["total_usd"])

    def test_pricing_falls_back_to_the_actual_response_model(self):
        # Requested model has no price; the versioned model reported in the
        # response does — accounting must use that fallback.
        engine = _PricingEngine({"model-x-04-28": (2.0, 4.0)})
        completion = _completion(
            "model-x", "model-x-04-28",
            {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
        )
        record = make_call_record(1, "utility", completion, engine)
        self.assertAlmostEqual(record["cost"]["input_usd"], 2.0)
        self.assertAlmostEqual(record["cost"]["output_usd"], 4.0)
        self.assertAlmostEqual(record["cost"]["total_usd"], 6.0)


class RecordShapeTest(unittest.TestCase):
    def test_record_carries_index_label_latency_and_response_metadata(self):
        engine = _PricingEngine({})
        completion = _completion(
            "model-x", "model-x-actual",
            {"prompt_tokens": 1, "completion_tokens": 1},
        )
        record = make_call_record(7, "validation", completion, engine)
        self.assertEqual(record["index"], 7)
        self.assertEqual(record["label"], "validation")
        self.assertEqual(record["latency_ms"], 12.5)
        self.assertEqual(record["request"], {"model": "model-x"})
        self.assertEqual(record["response"]["content"], "hello")
        self.assertEqual(record["response"]["finish_reason"], "stop")
        # The actual model reported in the response wins over the requested one.
        self.assertEqual(record["response"]["model"], "model-x-actual")
        self.assertEqual(record["response"]["id"], "resp-1")


if __name__ == "__main__":
    unittest.main()
