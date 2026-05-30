import asyncio
import sys
import tempfile
import unittest

from loom_core.agent_adapters.process_adapter import ProcessAgentAdapter

_PY = sys.executable


class ProcessAdapterTests(unittest.TestCase):
    def test_rejects_unknown_adapter_id(self):
        with self.assertRaises(ValueError):
            ProcessAgentAdapter(adapter_id="", command=["nonexistent"])

    def test_cancel_idempotent_before_start(self):
        adapter = ProcessAgentAdapter(
            adapter_id="test-worker",
            command=[_PY, "-c", "print('ok')"],
        )
        try:
            asyncio.run(adapter.cancel("run_not_started"))
        except Exception:
            self.fail("cancel before start should not raise")

    def test_invoke_unknown_task_returns_error_event(self):
        adapter = ProcessAgentAdapter(
            adapter_id="test-worker",
            command=[_PY, "-c", "print('ok')"],
        )

        async def run():
            events = []
            async for event in adapter.invoke({"taskId": "unknown", "type": "test"}):
                events.append(event)
            return events

        events = asyncio.run(run())
        self.assertGreater(len(events), 0)

    def test_invoke_rejects_empty_task(self):
        adapter = ProcessAgentAdapter(
            adapter_id="test-worker",
            command=[_PY, "-c", "print('ok')"],
        )

        async def run():
            with self.assertRaises(ValueError):
                async for _ in adapter.invoke({}):
                    pass

        asyncio.run(run())


    def test_cwd_from_task_envelope(self):
        """ProcessAgentAdapter must run subprocess in hand_dir from task envelope."""
        tmpdir = tempfile.mkdtemp()
        adapter = ProcessAgentAdapter(
            adapter_id="test-cwd",
            command=[
                _PY, "-c",
                "import os,json,sys; d=json.loads(sys.stdin.read()); print(json.dumps({'type':'run.artifact','artifact':{'cwd':os.getcwd()}}))",
            ],
        )

        async def run():
            events = []
            async for e in adapter.invoke({"task": "test", "hand_dir": tmpdir}):
                events.append(e)
            return events

        events = asyncio.run(run())
        artifact_events = [e for e in events if e.get("type") == "run.artifact"]
        self.assertEqual(len(artifact_events), 1)
        import os
        self.assertEqual(
            os.path.normcase(artifact_events[0]["artifact"]["cwd"]),
            os.path.normcase(tmpdir),
        )


if __name__ == "__main__":
    unittest.main()
