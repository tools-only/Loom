from __future__ import annotations

import unittest

from loom.brain_harness.orchestration import build_minimal_orchestration_snapshot


class OrchestrationSnapshotTests(unittest.TestCase):
    def test_builds_minimal_graph_from_hand_plan_and_artifacts(self):
        snapshot = build_minimal_orchestration_snapshot(
            episode_id="ep-1",
            goal="assess market risk",
            domain="finance",
            workflow={"mode": "state_driven", "rationale": "need evidence"},
            hand_plan={
                "tasks": [
                    {
                        "task_id": "t1",
                        "hand_id": "runtime-evidence",
                        "executor_id": "market",
                        "task": "Collect evidence",
                        "dimension": "evidence",
                        "capabilities": ["market_data"],
                        "depends_on": [],
                    }
                ],
                "rationale": "need evidence",
            },
            hand_artifacts={
                "t1": {
                    "metadata": {
                        "confidence": 0.8,
                        "key_claims": ["claim 1"],
                        "gaps": [],
                    }
                }
            },
        )

        node_ids = {node["id"] for node in snapshot["nodes"]}
        self.assertIn("brain", node_ids)
        self.assertIn("task:t1", node_ids)
        self.assertIn("hand:runtime-evidence", node_ids)
        self.assertIn("artifact:t1", node_ids)
        self.assertEqual("state_driven", snapshot["workflow_mode"])
        self.assertEqual(["market_data"], snapshot["profiles"]["runtime-evidence"]["capabilities"])


if __name__ == "__main__":
    unittest.main()
