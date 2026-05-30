from pathlib import Path
import unittest


class CoreAgentReserveTests(unittest.TestCase):
    def test_core_agent_import_is_optional(self):
        try:
            from loom_core.agents.core_agent import LoomCoreAgent
        except ImportError:
            self.skipTest("core_agent module not yet available")

    def test_core_agent_is_non_blocking(self):
        from loom_core.agents.core_agent import LoomCoreAgent
        agent = LoomCoreAgent()
        self.assertFalse(agent.is_running)
        self.assertIsNone(agent.suggest("test query"))

    def test_core_agent_does_not_block_startup(self):
        from loom_core.agents.core_agent import LoomCoreAgent
        from loom_core.runtime.core_agent_bridge import CoreAgentBridge
        from loom_core.runtime.app import LoomCoreRuntime

        root = Path(__file__).resolve().parents[1]
        runtime = LoomCoreRuntime(root_dir=root)
        agent = LoomCoreAgent()
        bridge = CoreAgentBridge(runtime=runtime, core_agent=agent)
        runtime.bootstrap()

        # bridge should not block boot
        self.assertIsNotNone(bridge)
        self.assertFalse(agent.is_running)

    def test_core_agent_bridge_returns_none_without_agent(self):
        from loom_core.runtime.core_agent_bridge import CoreAgentBridge
        from loom_core.runtime.app import LoomCoreRuntime

        root = Path(__file__).resolve().parents[1]
        runtime = LoomCoreRuntime(root_dir=root)
        runtime.bootstrap()
        bridge = CoreAgentBridge(runtime=runtime, core_agent=None)
        result = bridge.route("test.query", {"key": "value"})
        self.assertIsNone(result)

    def test_suggest_returns_none_when_idle(self):
        from loom_core.agents.core_agent import LoomCoreAgent
        agent = LoomCoreAgent()
        result = agent.suggest("any query")
        self.assertIsNone(result)

    def test_core_agent_bridge_surfaces_agent_suggestions(self):
        from loom_core.agents.core_agent import LoomCoreAgent
        from loom_core.runtime.core_agent_bridge import CoreAgentBridge
        from loom_core.runtime.app import LoomCoreRuntime

        root = Path(__file__).resolve().parents[1]
        runtime = LoomCoreRuntime(root_dir=root)
        runtime.bootstrap()
        agent = LoomCoreAgent()
        bridge = CoreAgentBridge(runtime=runtime, core_agent=agent)
        result = bridge.route("workspace.summarize", {"workspace_id": "ws_1"})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
