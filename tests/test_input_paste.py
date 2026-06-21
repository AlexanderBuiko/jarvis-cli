"""Tests for clipboard-paste collapsing in the input controller."""

import unittest

from jarvis.repl.input import InputController, PASTE_COLLAPSE_THRESHOLD


class PasteCollapseTest(unittest.TestCase):
    def setUp(self):
        self.ic = InputController()

    def test_register_paste_placeholder_format(self):
        data = "x" * 1500
        ph = self.ic._register_paste(data)
        self.assertEqual(ph, "[Pasted from clipboard: 1500 characters]")
        self.assertEqual(self.ic._pastes[ph], data)

    def test_expand_restores_original_text(self):
        data = "y" * (PASTE_COLLAPSE_THRESHOLD + 200)
        ph = self.ic._register_paste(data)
        buffer_text = f"please summarise {ph} thanks"
        self.assertEqual(
            self.ic._expand_pastes(buffer_text),
            f"please summarise {data} thanks",
        )

    def test_text_without_placeholder_is_unchanged(self):
        self.ic._register_paste("z" * 1200)
        self.assertEqual(self.ic._expand_pastes("nothing pasted here"), "nothing pasted here")

    def test_same_length_distinct_pastes_get_distinct_placeholders(self):
        a = "a" * 1100
        b = "b" * 1100
        ph_a = self.ic._register_paste(a)
        ph_b = self.ic._register_paste(b)
        self.assertNotEqual(ph_a, ph_b)
        self.assertEqual(self.ic._expand_pastes(ph_b), b)


class TaskAttachCompletionTest(unittest.TestCase):
    """attach / detach autocomplete as task subcommands."""

    def test_prefix_completes_attach_and_detach(self):
        from jarvis.repl.input import get_suggestions, apply_suggestion
        self.assertEqual(get_suggestions("task at"), ["attach"])
        self.assertEqual(get_suggestions("task det"), ["detach"])
        # 'de' is ambiguous between delete and detach — both are offered.
        self.assertEqual(set(get_suggestions("task de")), {"delete", "detach"})
        # Accepting the suggestion produces the full command.
        self.assertEqual(apply_suggestion("task at", "attach"), "task attach")


if __name__ == "__main__":
    unittest.main()
