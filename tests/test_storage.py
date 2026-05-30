import json
import os
import tempfile
import unittest

from loom_core.storage.event_log import EventLog
from loom_core.storage.sqlite_store import SqliteStore


class EventLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "events.jsonl")
        self.log = EventLog(self.log_path)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
        os.rmdir(self.tmp)

    def test_appends_and_reloads_events(self):
        self.log.append({"type": "test.event", "data": "hello"})
        self.log.append({"type": "test.event2", "data": "world"})
        events = self.log.reload()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["data"], "hello")
        self.assertEqual(events[1]["data"], "world")

    def test_append_adds_timestamp(self):
        self.log.append({"type": "test.event"})
        events = self.log.reload()
        self.assertIn("timestamp", events[0])

    def test_reload_empty_log(self):
        events = self.log.reload()
        self.assertEqual(events, [])


class SqliteStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        self.store = SqliteStore(self.db_path)

    def tearDown(self):
        self.store.close()
        import time
        for _ in range(5):
            try:
                for f in os.listdir(self.tmp):
                    fp = os.path.join(self.tmp, f)
                    os.remove(fp)
                os.rmdir(self.tmp)
                break
            except PermissionError:
                time.sleep(0.2)

    def test_initializes_tables(self):
        self.store.initialize()
        tables = self.store.list_tables()
        self.assertIn("events", tables)
        self.assertIn("artifacts", tables)
        self.assertIn("claims", tables)

    def test_inserts_and_queries_event(self):
        self.store.initialize()
        event_id = self.store.insert_event(
            event_type="test.event", payload={"data": "hello"}
        )
        self.assertIsNotNone(event_id)
        event = self.store.get_event(event_id)
        self.assertEqual(event["event_type"], "test.event")
        self.assertEqual(event["payload"]["data"], "hello")

    def test_double_initialize_is_safe(self):
        self.store.initialize()
        self.store.initialize()
        tables = self.store.list_tables()
        self.assertIn("events", tables)


if __name__ == "__main__":
    unittest.main()
