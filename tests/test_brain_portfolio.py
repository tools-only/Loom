import tempfile
import unittest
import base64
import zipfile
from io import BytesIO
from pathlib import Path

from loom.brain_portfolio import PortfolioDataHub


class PortfolioDataHubTest(unittest.TestCase):
    def test_source_token_is_stored_but_never_returned_in_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = PortfolioDataHub(Path(tmp))

            source = hub.upsert_source({
                "id": "notion-main",
                "type": "notion",
                "name": "Notion Portfolio",
                "api_token": "secret-token",
                "database_id": "db-123",
            })

            self.assertEqual(source["status"], "configured")
            self.assertNotIn("api_token", source)
            listed = hub.list_sources()[0]
            self.assertEqual(listed["id"], "notion-main")
            self.assertEqual(listed["status"], "configured")
            self.assertEqual(listed["auth"]["configured"], True)
            self.assertNotIn("secret-token", str(listed))

    def test_import_position_text_builds_canonical_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = PortfolioDataHub(Path(tmp))

            snapshot = hub.import_position_text(
                "ticker,quantity,avg_cost,market_price,currency\n"
                "NVDA,10,100,120,USD\n"
                "AAPL,5,200,190,USD\n",
                source_id="local-upload-1",
            )

            self.assertEqual(snapshot["position_count"], 2)
            self.assertEqual(snapshot["totals"]["market_value"], 2150.0)
            self.assertEqual(snapshot["totals"]["cost_basis"], 2000.0)
            self.assertEqual(snapshot["totals"]["unrealized_pnl"], 150.0)
            self.assertEqual(snapshot["watch_targets"], ["NVDA", "AAPL"])
            self.assertEqual(snapshot["positions"][0]["ticker"], "NVDA")
            self.assertAlmostEqual(snapshot["positions"][0]["weight"], 1200.0 / 2150.0)

    def test_hand_payload_contains_only_redacted_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = PortfolioDataHub(Path(tmp))
            hub.upsert_source({
                "id": "google-sheet",
                "type": "google_docs",
                "name": "Google Position Sheet",
                "api_token": "google-secret",
            })
            hub.import_position_text(
                "ticker,quantity,avg_cost,market_price\nMSFT,3,300,330\n",
                source_id="google-sheet",
            )

            payload = hub.build_hand_payload()

            self.assertEqual(payload["source"], "brain.portfolio_data_hub")
            self.assertEqual(payload["portfolio_summary"]["position_count"], 1)
            self.assertEqual(payload["top_positions"][0]["ticker"], "MSFT")
            self.assertNotIn("api_token", str(payload))
            self.assertNotIn("google-secret", str(payload))
            self.assertNotIn("raw_rows", str(payload))

    def test_import_docx_file_extracts_text_and_builds_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = PortfolioDataHub(Path(tmp))
            buf = BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr(
                    "word/document.xml",
                    "<w:document><w:body><w:t>ticker,quantity,avg_cost,market_price</w:t>"
                    "<w:t>TSLA,2,180,210</w:t></w:body></w:document>",
                )

            snapshot = hub.import_file({
                "file_name": "positions.docx",
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "content_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
                "source_id": "docx-upload",
            })

            self.assertEqual(snapshot["position_count"], 1)
            self.assertEqual(snapshot["watch_targets"], ["TSLA"])


if __name__ == "__main__":
    unittest.main()
