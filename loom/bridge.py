"""HTTP client — connects Python Loom harness to the JS server at port 3000."""
import json
import time
from pathlib import Path
import httpx

SERVER_URL = "http://127.0.0.1:3000"
ROOT = Path(__file__).parent.parent
THESIS_STORE = ROOT / "logs" / "thesis-store.jsonl"


async def get_connector_data(connector_id: str, params: dict = {}) -> dict | None:
    async with httpx.AsyncClient() as c:
        try:
            r = await c.get(f"{SERVER_URL}/data/{connector_id}", params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
    return None


async def patch_webview(anchor_id: str, html_fragment: str) -> bool:
    payload = {"patches": [{"anchor_id": anchor_id, "html_fragment": html_fragment}]}
    async with httpx.AsyncClient() as c:
        try:
            r = await c.post(f"{SERVER_URL}/patch", json=payload, timeout=10)
            return r.status_code == 200
        except Exception:
            return False


async def get_thesis(ticker: str) -> dict | None:
    async with httpx.AsyncClient() as c:
        try:
            r = await c.get(f"{SERVER_URL}/loom/thesis/{ticker}", timeout=5)
            if r.status_code == 200:
                return r.json().get("thesis")
        except Exception:
            pass
    return None


def append_thesis(ticker: str, artifact: dict):
    THESIS_STORE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ticker": ticker.upper(),
        "ts": time.time(),
        "confidence": artifact.get("metadata", {}).get("confidence", 0),
        "gaps": artifact.get("metadata", {}).get("gaps", []),
        "key_claims": artifact.get("metadata", {}).get("key_claims", []),
        "narrative": artifact.get("narrative", ""),
    }
    with open(THESIS_STORE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
