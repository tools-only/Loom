import unittest

from loom_core.interaction_protocol.envelope import (
    HumanIntentEnvelope,
    normalize_human_intent_envelope,
)


class InteractionProtocolTests(unittest.TestCase):
    def test_normalizes_current_human_intent_fields(self):
        envelope = normalize_human_intent_envelope(
            {
                "eventId": "evt_1",
                "workspaceId": "workspace_1",
                "fileId": "file_1",
                "targetAnchor": "analysis.summary",
                "op": "refine",
                "instruction": "make it sharper",
                "selection": {"text": "selected text"},
                "domain": "loom-fin",
            }
        )

        self.assertIsInstance(envelope, HumanIntentEnvelope)
        self.assertEqual(envelope.event_id, "evt_1")
        self.assertEqual(envelope.workspace_id, "workspace_1")
        self.assertEqual(envelope.file_id, "file_1")
        self.assertEqual(envelope.target_anchor, "analysis.summary")
        self.assertEqual(envelope.op, "refine")
        self.assertEqual(envelope.instruction, "make it sharper")
        self.assertEqual(envelope.selection["text"], "selected text")
        self.assertEqual(envelope.domain, "loom-fin")

    def test_requires_op(self):
        with self.assertRaises(ValueError):
            normalize_human_intent_envelope({"instruction": "missing op"})

    def test_supports_existing_webview_ops(self):
        for op in [
            "ask",
            "refine",
            "expand",
            "shorten",
            "longer",
            "edit",
            "annotate",
            "branch",
            "review",
            "restructure",
            "lock",
        ]:
            envelope = normalize_human_intent_envelope({"op": op})
            self.assertEqual(envelope.op, op)


if __name__ == "__main__":
    unittest.main()
