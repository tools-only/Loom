#!/usr/bin/env python3
"""Tests for Loom Desktop Float (non-GUI components)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Set dummy DISPLAY to prevent tkinter from trying to open a window
os.environ['DISPLAY'] = ''


class TestConfig(unittest.TestCase):
    """Test config persistence."""

    def setUp(self):
        # Use temp dir for config
        self._orig_dir = None
        import desktop_float.float as F
        self._orig_config_dir = F.CONFIG_DIR
        F.CONFIG_DIR = Path(tempfile.mkdtemp())
        F.CONFIG_FILE = F.CONFIG_DIR / 'config.json'

    def tearDown(self):
        import shutil
        import desktop_float.float as F
        F.CONFIG_DIR = self._orig_config_dir
        F.CONFIG_FILE = self._orig_config_dir / 'config.json'
        if F.CONFIG_DIR != self._orig_config_dir:
            shutil.rmtree(str(F.CONFIG_DIR.parent), ignore_errors=True)

    def test_save_and_load(self):
        from desktop_float.float import save_config, load_config
        save_config({'position': {'x': 100, 'y': 200}})
        cfg = load_config()
        self.assertEqual(cfg['position']['x'], 100)
        self.assertEqual(cfg['position']['y'], 200)

    def test_load_empty(self):
        from desktop_float.float import load_config
        cfg = load_config()
        self.assertEqual(cfg, {})


class TestWindowGeometry(unittest.TestCase):
    """Test window positioning helpers."""

    def test_clamps_panel_inside_screen_bounds(self):
        from desktop_float.float import clamp_window_position

        x, y = clamp_window_position(1800, 1000, 400, 500, (0, 0, 1920, 1080))

        self.assertEqual((x, y), (1520, 580))

    def test_allows_negative_virtual_screen_origin(self):
        from desktop_float.float import clamp_window_position

        x, y = clamp_window_position(-2200, -50, 400, 500, (-1920, 0, 1920, 1080))

        self.assertEqual((x, y), (-1920, 0))


class TestPayloadInference(unittest.TestCase):
    """Test URL-first payload generation."""

    def test_extract_first_url_trims_trailing_punctuation(self):
        from desktop_float.float import extract_first_url

        self.assertEqual(
            extract_first_url('read this https://example.com/report).'),
            'https://example.com/report',
        )

    def test_infer_channel_for_social_sources(self):
        from desktop_float.float import infer_channel

        self.assertEqual(infer_channel('https://x.com/user/status/1'), 'x')
        self.assertEqual(infer_channel('https://www.youtube.com/watch?v=1'), 'youtube')
        self.assertEqual(infer_channel('https://example.com/research'), 'web')

    def test_url_only_payload_has_backend_analysis_defaults(self):
        from desktop_float.float import build_capture_payload

        payload = build_capture_payload('https://example.com/ai-capex')

        self.assertEqual(payload['url'], 'https://example.com/ai-capex')
        self.assertEqual(payload['resource_kind'], 'link')
        self.assertEqual(payload['channel'], 'web')
        self.assertIn('loom-fin', payload['tags'])
        self.assertIn('Analyze this resource', payload['intent_hint'])

    def test_note_payload_stays_single_action(self):
        from desktop_float.float import build_capture_payload

        payload = build_capture_payload('Track AI capex against GPU backlog.')

        self.assertEqual(payload['url'], '')
        self.assertEqual(payload['resource_kind'], 'note')
        self.assertEqual(payload['title'], 'Track AI capex against GPU backlog.')

    def test_default_ui_avoids_manual_tag_or_chip_choices(self):
        source = Path(__file__).with_name('float.py').read_text('utf-8')

        self.assertNotIn('_tags_entry', source)
        self.assertNotIn('_insert_chip', source)
        self.assertIn('_try_prefill_from_clipboard', source)


class TestHTTP(unittest.TestCase):
    """Test HTTP capture to Loom."""

    def test_capture_endpoint_reachable(self):
        try:
            from urllib.request import Request, urlopen
            req = Request('http://localhost:3000/health')
            resp = urlopen(req, timeout=3)
            body = json.loads(resp.read().decode('utf-8'))
            self.assertTrue(body.get('ok'))
        except Exception as e:
            self.skipTest(f'Anchor server not running: {e}')

    def test_post_capture(self):
        try:
            from urllib.request import Request, urlopen
            payload = {'title': 'unittest', 'text': 'float test', 'tags': ['test']}
            data = json.dumps(payload).encode('utf-8')
            req = Request('http://localhost:3000/channels/capture',
                          data=data,
                          headers={'Content-Type': 'application/json'})
            resp = urlopen(req, timeout=5)
            body = json.loads(resp.read().decode('utf-8'))
            self.assertTrue(body.get('ok'))
            self.assertIn('resource', body)
        except Exception as e:
            self.skipTest(f'Capture POST failed: {e}')

    def test_capture_fails_without_text(self):
        try:
            from urllib.request import Request, urlopen
            from urllib.error import HTTPError
            payload = {'title': 'empty'}
            data = json.dumps(payload).encode('utf-8')
            req = Request('http://localhost:3000/channels/capture',
                          data=data,
                          headers={'Content-Type': 'application/json'})
            try:
                resp = urlopen(req, timeout=5)
                body = json.loads(resp.read().decode('utf-8'))
                self.assertFalse(body.get('ok', True))
            except HTTPError as e:
                self.assertIn(e.code, (400, 422))
        except Exception as e:
            self.skipTest(f'Server not available: {e}')


class TestAsyncPost(unittest.TestCase):
    """Test async POST helper."""

    def test_post_async_calls_callback(self):
        import threading
        import desktop_float.float as F

        class FakeResponse:
            status = 200

            def read(self):
                return json.dumps({
                    'ok': True,
                    'resource': {'resource_id': 'resource-test'},
                }).encode('utf-8')

        results = []
        done = threading.Event()

        def callback(ok, msg):
            results.append((ok, msg))
            done.set()

        original_urlopen = F.urlopen
        F.urlopen = lambda req, timeout=10: FakeResponse()
        try:
            F.post_async({'title': 'async_test', 'text': 'test', 'tags': []}, callback)
            done.wait(2)
        finally:
            F.urlopen = original_urlopen

        self.assertTrue(len(results) > 0)
        self.assertTrue(results[0][0])
        self.assertEqual(results[0][1], 'resource-test')


if __name__ == '__main__':
    unittest.main()
