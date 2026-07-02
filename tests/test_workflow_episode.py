import tempfile
import unittest
from pathlib import Path

from loom.brain_harness.workflow_episode import WorkflowEpisode


class WorkflowEpisodeEventSinkTests(unittest.TestCase):
    def test_delivers_each_persisted_event_to_sink(self):
        received = []
        episode = WorkflowEpisode.new(
            goal="research NVDA",
            event_sink=received.append,
        )

        with tempfile.TemporaryDirectory() as directory:
            episode.write_event(Path(directory), "episode.start", {"request_id": "msg-1"})
            episode.transition(Path(directory), "Dispatching")

        self.assertEqual(["episode.start", "state.transition"], [event["type"] for event in received])
        self.assertTrue(all(event["episode_id"] == episode.episode_id for event in received))

    def test_persists_new_event_families(self):
        received = []
        episode = WorkflowEpisode.new(goal="test states", event_sink=received.append)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            episode.write_event(root, "state.proposed", {"state_id": "S1", "state_type": "claim"})
            episode.write_event(root, "state.transition", {"state_id": "S1", "from": "active", "to": "contested"})
            episode.write_event(root, "claim.created", {"claim": "test claim"})
            episode.write_event(root, "gap.detected", {"gap": "missing evidence"})
            episode.write_event(root, "bottleneck.detected", {"bottleneck_id": "B1"})
            episode.write_event(root, "visual.query_created", {"query_id": "vq_1"})
            episode.write_event(root, "visual.interaction", {"interaction_id": "vi_1"})
            episode.write_event(root, "state.used_by_synthesis", {"state_id": "S1"})

        types = [e["type"] for e in received]
        for expected in ("state.proposed", "visual.interaction", "state.used_by_synthesis"):
            self.assertIn(expected, types)


if __name__ == "__main__":
    unittest.main()
