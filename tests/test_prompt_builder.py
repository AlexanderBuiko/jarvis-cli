"""Tests for prompt construction (jarvis.prompt_builder.builder).

All functions here are pure string/message assembly — no network, no state. The
system-prompt assembly is exercised without a task so the test stays inside this
module (the task-stage path is covered in test_stage_agents).
"""

import unittest

from jarvis.prompt_builder.builder import (
    build_system_prompt,
    build_strategy_prompt,
    build_working_memory_block,
    build_attachments_block,
    build_rag_block,
    build_invariant_check_prompt,
    build_invariant_resolution_prompt,
    build_summary_prompt,
    build_dialogue_state_prompt,
    build_topic_routing_prompt,
    build_prompt_generation_request,
)


class SystemPromptTest(unittest.TestCase):
    def test_default_params_yield_only_the_base_prompt(self):
        prompt = build_system_prompt({})
        self.assertIn("You are Jarvis", prompt)
        self.assertNotIn("step by step", prompt)
        self.assertNotIn("panel of three", prompt)

    def test_step_by_step_strategy_appends_its_instruction(self):
        prompt = build_system_prompt({"solution_strategy": "step_by_step"})
        self.assertIn("step by step", prompt)

    def test_expert_panel_strategy_appends_its_instruction(self):
        prompt = build_system_prompt({"solution_strategy": "expert_panel"})
        self.assertIn("panel of three", prompt)

    def test_known_task_template_is_appended(self):
        prompt = build_system_prompt({"task_template": "android_interview"})
        self.assertIn("Android/Kotlin", prompt)

    def test_unknown_task_template_is_ignored(self):
        prompt = build_system_prompt({"task_template": "does_not_exist"})
        self.assertNotIn("Android/Kotlin", prompt)

    def test_profile_and_invariants_are_injected_when_present(self):
        prompt = build_system_prompt(
            {}, profile="Keep answers short.", invariants="Never delete data."
        )
        self.assertIn("User Profile", prompt)
        self.assertIn("Keep answers short.", prompt)
        self.assertIn("Invariants", prompt)
        self.assertIn("Never delete data.", prompt)

    def test_blank_profile_and_invariants_add_no_block(self):
        prompt = build_system_prompt({}, profile="   ", invariants="")
        self.assertNotIn("User Profile", prompt)
        self.assertNotIn("hard rules", prompt)


class StrategyPromptTest(unittest.TestCase):
    def test_direct_strategy_passes_the_request_through_unchanged(self):
        self.assertEqual(build_strategy_prompt({}, "hi"), "hi")

    def test_step_by_step_wraps_the_request(self):
        wrapped = build_strategy_prompt({"solution_strategy": "step_by_step"}, "solve x")
        self.assertIn("step by step", wrapped)
        self.assertTrue(wrapped.endswith("solve x"))

    def test_expert_panel_wraps_the_request(self):
        wrapped = build_strategy_prompt({"solution_strategy": "expert_panel"}, "solve x")
        self.assertIn("panel of three experts", wrapped)
        self.assertTrue(wrapped.endswith("solve x"))


class WorkingMemoryBlockTest(unittest.TestCase):
    def test_block_is_a_two_message_pseudo_exchange(self):
        block = build_working_memory_block({"name": "T", "stage": "planning"})
        self.assertEqual(len(block), 2)
        self.assertEqual(block[0]["role"], "user")
        self.assertEqual(block[1]["role"], "assistant")

    def test_block_carries_stage_plan_and_current_step(self):
        task = {
            "name": "Fix bug",
            "stage": "execution",
            "current_step": "edit loop.py",
            "plan": "1. read\n2. edit",
        }
        content = build_working_memory_block(task)[0]["content"]
        self.assertIn("Fix bug", content)
        self.assertIn("Stage: execution", content)
        self.assertIn("edit loop.py", content)
        self.assertIn("1. read", content)

    def test_only_the_preceding_stage_output_is_included(self):
        task = {
            "name": "T",
            "stage": "execution",
            "stage_outputs": {"planning": "the approved plan"},
        }
        content = build_working_memory_block(task)[0]["content"]
        self.assertIn("previous stage [planning]", content)
        self.assertIn("the approved plan", content)


class ReferenceBlockTest(unittest.TestCase):
    def test_empty_attachments_produce_no_block(self):
        self.assertEqual(build_attachments_block([]), [])

    def test_attachments_block_renders_name_and_content(self):
        block = build_attachments_block(
            [{"name": "research", "summary": "findings", "content": "body text"}]
        )
        content = block[0]["content"]
        self.assertIn("research", content)
        self.assertIn("findings", content)
        self.assertIn("body text", content)

    def test_empty_rag_results_produce_no_block(self):
        self.assertEqual(build_rag_block([]), [])

    def test_rag_block_numbers_and_cites_each_excerpt(self):
        block = build_rag_block(
            [{"text": "chunk one", "metadata": {"filename": "kb.md", "section": "Intro"}}]
        )
        content = block[0]["content"]
        self.assertIn("[1] kb.md", content)
        self.assertIn("Intro", content)
        self.assertIn("chunk one", content)


class InvariantPromptTest(unittest.TestCase):
    def test_check_prompt_omits_tool_block_by_default(self):
        prompt = build_invariant_check_prompt("R1", "some reply")
        self.assertIn("R1", prompt)
        self.assertIn("some reply", prompt)
        self.assertNotIn("TOOL ACTIVITY", prompt)

    def test_check_prompt_includes_tool_block_when_context_given(self):
        prompt = build_invariant_check_prompt("R1", "reply", tool_context="weather: 20C")
        self.assertIn("TOOL ACTIVITY", prompt)
        self.assertIn("weather: 20C", prompt)

    def test_resolution_prompt_carries_invariants_reply_and_violations(self):
        prompt = build_invariant_resolution_prompt("R1", "bad reply", "broke R1")
        self.assertIn("R1", prompt)
        self.assertIn("bad reply", prompt)
        self.assertIn("broke R1", prompt)
        self.assertIn("CORRECTED:", prompt)
        self.assertIn("REFUSED:", prompt)


class MemoryPromptTest(unittest.TestCase):
    def test_summary_prompt_includes_existing_summary_and_new_turns(self):
        prompt = build_summary_prompt(
            "prior summary",
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}],
        )
        self.assertIn("prior summary", prompt)
        self.assertIn("User: hi", prompt)
        self.assertIn("Assistant: yo", prompt)

    def test_dialogue_state_prompt_requests_the_three_fixed_slots(self):
        prompt = build_dialogue_state_prompt(None, [{"role": "user", "content": "plan a trip"}])
        self.assertIn("Goal:", prompt)
        self.assertIn("Given:", prompt)
        self.assertIn("Constraints:", prompt)
        self.assertIn("plan a trip", prompt)

    def test_topic_routing_prompt_creates_first_topic_when_none_exist(self):
        prompt = build_topic_routing_prompt("kotlin coroutines", {})
        self.assertIn("kotlin coroutines", prompt)
        self.assertIn("kebab-case", prompt)

    def test_topic_routing_prompt_lists_existing_topics(self):
        prompt = build_topic_routing_prompt(
            "more on this", {"android-arch": "about architecture"}
        )
        self.assertIn("android-arch", prompt)
        self.assertIn("more on this", prompt)

    def test_prompt_generation_request_wraps_the_task(self):
        prompt = build_prompt_generation_request("summarise a paper")
        self.assertIn("summarise a paper", prompt)
        self.assertIn("Output only the prompt", prompt)


if __name__ == "__main__":
    unittest.main()
