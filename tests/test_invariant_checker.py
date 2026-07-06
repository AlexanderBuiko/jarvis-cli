"""Tests for the extracted InvariantChecker (the requirements linter)."""

import unittest

from jarvis.llm.gateway import LLMGateway
from jarvis.openrouter.client import Completion
from jarvis.pipeline.invariants import InvariantChecker, _invariants_ok
from tests.fake_engine import FakeEngine


def _dummy_completion() -> Completion:
    return Completion(
        text="original answer",
        finish_reason="stop",
        request={"model": "test/model"},
        response={"model": "test/model", "usage": {"total_tokens": 2}},
        latency_ms=0.0,
    )


class InvariantsOkTest(unittest.TestCase):
    def test_empty_is_ok(self):
        self.assertTrue(_invariants_ok(""))

    def test_ok_token(self):
        self.assertTrue(_invariants_ok("OK"))
        self.assertTrue(_invariants_ok("ok\n"))

    def test_violation_list_is_not_ok(self):
        self.assertFalse(_invariants_ok("- rule X : violated"))


class InvariantCheckerTest(unittest.TestCase):
    def test_compliant_reply_passes_unchanged(self):
        engine = FakeEngine(scripted=["OK"])
        checker = InvariantChecker(LLMGateway(engine))
        api_calls: list[dict] = []
        completion = _dummy_completion()

        text, notice, returned = checker.validate(
            invariants="Always answer in English.",
            messages=[{"role": "user", "content": "hi"}],
            response_text="original answer",
            completion=completion,
            params={"model": "test/model"},
            api_calls=api_calls,
        )

        self.assertEqual(text, "original answer")
        self.assertIsNone(notice)
        self.assertIs(returned, completion)
        # Exactly one call (the check); no rework.
        self.assertEqual(len(api_calls), 1)
        self.assertEqual(api_calls[0]["label"], "invariant_check")

    def test_check_and_resolution_use_separate_gateways(self):
        # The compliance CHECK runs on the (optionally local) check gateway; the
        # RESOLUTION that rewrites the user-facing answer runs on the main gateway.
        check_engine = FakeEngine(scripted=["- rule : violated"])
        main_engine = FakeEngine(scripted=["resolved on main"])
        checker = InvariantChecker(
            LLMGateway(check_engine), resolve_gateway=LLMGateway(main_engine)
        )
        api_calls: list[dict] = []

        text, notice, _ = checker.validate(
            invariants="Always answer in English.",
            messages=[{"role": "user", "content": "hi"}],
            response_text="bad answer",
            completion=_dummy_completion(),
            params={"model": "test/model"},
            api_calls=api_calls,
        )

        self.assertEqual(text, "resolved on main")
        self.assertIsNotNone(notice)
        self.assertEqual(len(check_engine.calls), 1)   # only the check
        self.assertEqual(len(main_engine.calls), 1)    # only the resolution
        self.assertEqual([c["label"] for c in api_calls],
                         ["invariant_check", "invariant_resolution"])

    def test_violation_triggers_single_resolution(self):
        engine = FakeEngine(scripted=["- rule : violated", "resolved answer"])
        checker = InvariantChecker(LLMGateway(engine))
        api_calls: list[dict] = []

        text, notice, returned = checker.validate(
            invariants="Always answer in English.",
            messages=[{"role": "user", "content": "hi"}],
            response_text="bad answer",
            completion=_dummy_completion(),
            params={"model": "test/model"},
            api_calls=api_calls,
        )

        self.assertEqual(text, "resolved answer")
        self.assertIsNotNone(notice)
        self.assertEqual([c["label"] for c in api_calls], ["invariant_check", "invariant_resolution"])
        # The resolution call must include the prior reply + the resolution instruction.
        resolution_messages = engine.calls[1][0]
        self.assertEqual(resolution_messages[-2]["content"], "bad answer")


if __name__ == "__main__":
    unittest.main()
