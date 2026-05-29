import json
import tempfile
import time
import unittest
from pathlib import Path

from loom_core.runtime.resource_provider import ResourceProviderRegistry
from loom_core.runtime.feedback_store import FeedbackStore
from loom_core.runtime.hand_config_store import HandConfigStore


class ResourceProviderRegistryTests(unittest.TestCase):
    def setUp(self):
        self.reg = ResourceProviderRegistry()

    def test_fetch_unknown_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.reg.fetch("nonexistent", {})

    def test_fetch_calls_registered_fetcher_with_params(self):
        captured = {}
        self.reg.register("test_source", lambda p: captured.update(p) or {"data": 1})
        result = self.reg.fetch("test_source", {"ticker": "NVDA"})
        self.assertEqual(captured, {"ticker": "NVDA"})
        self.assertEqual(result, {"data": 1})

    def test_list_ids_returns_registered(self):
        self.reg.register("a", lambda p: None)
        self.reg.register("b", lambda p: None)
        self.assertIn("a", self.reg.list_ids())
        self.assertIn("b", self.reg.list_ids())

    def test_register_overwrites_existing(self):
        self.reg.register("src", lambda p: "first")
        self.reg.register("src", lambda p: "second")
        self.assertEqual(self.reg.fetch("src", {}), "second")


class FeedbackStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = Path(self.tmpdir) / "logs" / "feedback.jsonl"
        self.store = FeedbackStore(self.log_path)

    def test_append_creates_file_and_read_returns_event(self):
        self.store.append({"hand_id": "market", "type": "thumbs_up"})
        events = self.store.read()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["hand_id"], "market")

    def test_append_adds_timestamp(self):
        before = time.time()
        self.store.append({"hand_id": "market"})
        after = time.time()
        events = self.store.read()
        self.assertGreaterEqual(events[0]["ts"], before)
        self.assertLessEqual(events[0]["ts"], after)

    def test_append_preserves_existing_timestamp(self):
        self.store.append({"hand_id": "market", "ts": 1000.0})
        events = self.store.read()
        self.assertEqual(events[0]["ts"], 1000.0)

    def test_read_filters_by_hand_id(self):
        self.store.append({"hand_id": "market"})
        self.store.append({"hand_id": "sentiment"})
        events = self.store.read(hand_id="market")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["hand_id"], "market")

    def test_read_filters_by_since(self):
        self.store.append({"hand_id": "market", "ts": 100.0})
        self.store.append({"hand_id": "market", "ts": 200.0})
        events = self.store.read(since=150.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["ts"], 200.0)

    def test_read_empty_when_no_file(self):
        store = FeedbackStore(Path(self.tmpdir) / "nonexistent" / "log.jsonl")
        self.assertEqual(store.read(), [])


class HandConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = HandConfigStore(Path(self.tmpdir))

    def test_read_returns_empty_dict_for_missing_hand(self):
        self.assertEqual(self.store.read("market"), {})

    def test_write_then_read_roundtrip(self):
        config = {"kols": ["Lyn Alden", "Dario Amodei"], "sectors": ["tech", "energy"]}
        self.store.write("market", config)
        result = self.store.read("market")
        self.assertEqual(result, config)

    def test_write_creates_directory(self):
        self.store.write("new_hand", {"x": 1})
        path = Path(self.tmpdir) / "new_hand" / "config.json"
        self.assertTrue(path.exists())

    def test_write_is_valid_json(self):
        self.store.write("market", {"key": "value"})
        path = Path(self.tmpdir) / "market" / "config.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["key"], "value")

    def test_overwrite_replaces_config(self):
        self.store.write("market", {"v": 1})
        self.store.write("market", {"v": 2})
        self.assertEqual(self.store.read("market"), {"v": 2})


if __name__ == "__main__":
    unittest.main()
