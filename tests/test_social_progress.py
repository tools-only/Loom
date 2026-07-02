import asyncio
import unittest

from loom_core.interaction_protocol.social_progress import DiscordProgress, DiscordProgressReporter


class DiscordProgressTests(unittest.TestCase):
    def test_direct_brain_reply_does_not_claim_it_is_waiting_for_dispatch(self):
        embed = DiscordProgress(stage="complete", direct_reply=True).discord_embed()

        self.assertEqual("Brain 直接回复", embed["fields"][0]["name"])
        self.assertIn("未派发 Hand Agent", embed["fields"][0]["value"])
        self.assertNotIn("已派发 0", embed["description"])

    def test_confirmation_prompt_is_reported_as_waiting_for_user(self):
        embed = DiscordProgress(stage="received", awaiting_confirmation=True).discord_embed()

        self.assertEqual("Loom 需要确认", embed["title"])
        self.assertEqual("等待用户回答", embed["fields"][0]["name"])

    def test_planning_failure_reports_error_instead_of_waiting_for_dispatch(self):
        progress = DiscordProgress()
        progress.apply({"type": "episode.start", "episode_id": "ep-plan"})
        progress.apply({
            "type": "episode.error",
            "message": "Brain agent command timed out after 180s",
        })
        progress.apply({"type": "state.transition", "from": "Planning", "to": "Failed"})

        embed = progress.discord_embed()

        self.assertEqual("Loom 任务失败", embed["title"])
        self.assertIn("规划失败", embed["fields"][0]["name"])
        self.assertIn("timed out", embed["fields"][0]["value"])

    def test_projects_hand_lifecycle_and_synthesis(self):
        progress = DiscordProgress()
        events = [
            {"type": "episode.start", "episode_id": "ep-1"},
            {"type": "dispatch.sent", "hand_id": "market", "dimension": "market regime"},
            {"type": "dispatch.sent", "hand_id": "sentiment", "dimension": "crowd positioning"},
            {"type": "dispatch.artifact", "hand_id": "market"},
            {"type": "dispatch.error", "hand_id": "sentiment", "message": "timeout"},
            {"type": "state.transition", "to": "Synthesizing"},
        ]

        for event in events:
            progress.apply(event)

        snapshot = progress.snapshot()
        self.assertEqual("ep-1", snapshot["episode_id"])
        self.assertEqual("synthesizing", snapshot["stage"])
        self.assertEqual(2, snapshot["hand_count"])
        self.assertEqual(["market"], snapshot["completed"])
        self.assertEqual(["sentiment"], snapshot["failed"])
        self.assertEqual([], snapshot["running"])

        embed = progress.discord_embed()
        self.assertIn("Brain 正在汇总", embed["title"])
        fields = {field["name"]: field["value"] for field in embed["fields"]}
        self.assertIn("market", fields["已完成 (1)"])
        self.assertIn("sentiment", fields["失败 (1)"])

    def test_marks_persisted_episode_complete(self):
        progress = DiscordProgress()
        progress.apply({"type": "episode.start", "episode_id": "ep-2"})
        progress.apply({"type": "state.transition", "to": "Persisted"})

        self.assertEqual("complete", progress.snapshot()["stage"])
        self.assertIn("已完成", progress.discord_embed()["title"])

    def test_hand_remains_running_until_all_of_its_tasks_finish(self):
        progress = DiscordProgress()
        progress.apply({"type": "dispatch.sent", "hand_id": "market", "task_id": "t1"})
        progress.apply({"type": "dispatch.sent", "hand_id": "market", "task_id": "t2"})
        progress.apply({"type": "dispatch.artifact", "hand_id": "market", "task_id": "t1"})

        self.assertEqual(["market"], progress.snapshot()["running"])
        self.assertEqual([], progress.snapshot()["completed"])

        progress.apply({"type": "dispatch.artifact", "hand_id": "market", "task_id": "t2"})
        self.assertEqual([], progress.snapshot()["running"])
        self.assertEqual(["market"], progress.snapshot()["completed"])

    def test_reporter_coalesces_events_and_flushes_latest_state(self):
        published = []

        async def publish(embed):
            published.append(embed)

        async def run():
            reporter = DiscordProgressReporter(publish, debounce_seconds=0.01)
            reporter.notify({"type": "dispatch.sent", "episode_id": "ep-3", "hand_id": "market"})
            reporter.notify({"type": "dispatch.artifact", "episode_id": "ep-3", "hand_id": "market"})
            reporter.notify({"type": "state.transition", "episode_id": "ep-3", "to": "Persisted"})
            await reporter.flush()

        asyncio.run(run())
        self.assertEqual(1, len(published))
        self.assertIn("已完成", published[0]["title"])


    def test_reporter_flush_retries_a_failed_background_publish(self):
        attempts = []
        published = []

        async def publish(embed):
            attempts.append(embed)
            if len(attempts) == 1:
                raise RuntimeError("temporary Discord edit failure")
            published.append(embed)

        async def run():
            reporter = DiscordProgressReporter(publish, debounce_seconds=0.01)
            reporter.notify({"type": "state.transition", "episode_id": "ep-retry", "to": "Persisted"})
            await asyncio.sleep(0.02)
            await reporter.flush()

        asyncio.run(run())
        self.assertEqual(2, len(attempts))
        self.assertEqual(1, len(published))


if __name__ == "__main__":
    unittest.main()
