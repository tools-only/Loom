from __future__ import annotations

import csv
import base64
import datetime as _dt
import json
import re
import uuid
import zipfile
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any


class PortfolioDataHub:
    """Brain-owned portfolio source registry, normalizer, and snapshot store.

    Raw source credentials and imported rows stay in Brain storage. Hand agents
    receive only the redacted summary produced by build_hand_payload().
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.dir = self.root / "brain" / "portfolio"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sources_path = self.dir / "sources.json"
        self.secrets_path = self.dir / "secrets.json"
        self.snapshot_path = self.dir / "snapshot.json"
        self.raw_rows_path = self.dir / "raw_rows.json"

    def list_sources(self) -> list[dict[str, Any]]:
        sources = self._read_json(self.sources_path, [])
        secrets = self._read_json(self.secrets_path, {})
        return [self._public_source(src, secrets) for src in sources]

    def upsert_source(self, data: dict[str, Any]) -> dict[str, Any]:
        sources = self._read_json(self.sources_path, [])
        secrets = self._read_json(self.secrets_path, {})
        source_id = self._source_id(data)
        source_type = str(data.get("type") or "local_file")
        now = _now()
        existing = next((src for src in sources if src.get("id") == source_id), {})
        configured = bool(self._extract_secret(data)) or source_type in ("local_file", "manual")
        source = {
            **existing,
            "id": source_id,
            "type": source_type,
            "name": str(data.get("name") or existing.get("name") or source_id),
            "status": "configured" if configured else existing.get("status", "pending"),
            "config": self._public_config(data, source_type),
            "updated_at": now,
            "created_at": existing.get("created_at") or now,
        }
        sources = [src for src in sources if src.get("id") != source_id] + [source]
        secret = self._extract_secret(data)
        if secret:
            secrets[source_id] = {"secret": secret, "updated_at": now}
        self._write_json(self.sources_path, sources)
        self._write_json(self.secrets_path, secrets)
        return self._public_source(source, secrets)

    def get_snapshot(self) -> dict[str, Any]:
        return self._read_json(self.snapshot_path, self._empty_snapshot())

    def import_position_text(self, text: str, source_id: str = "manual") -> dict[str, Any]:
        raw_rows = self._parse_rows(text)
        positions = [pos for row in raw_rows if (pos := self._row_to_position(row, source_id))]
        snapshot = self._build_snapshot(positions, source_id)
        self._write_json(self.raw_rows_path, {
            "source_id": source_id,
            "imported_at": snapshot["updated_at"],
            "rows": raw_rows,
        })
        self._write_json(self.snapshot_path, snapshot)
        return snapshot

    def import_file(self, data: dict[str, Any]) -> dict[str, Any]:
        file_name = str(data.get("file_name") or "upload")
        mime_type = str(data.get("mime_type") or "")
        source_id = str(data.get("source_id") or self._source_id({"name": file_name, "type": "local_file"}))
        content = base64.b64decode(str(data.get("content_base64") or ""))
        self.upsert_source({
            "id": source_id,
            "type": "local_file",
            "name": file_name,
            "file_name": file_name,
            "mime_type": mime_type,
        })
        lower_name = file_name.lower()
        if lower_name.endswith(".docx") or "wordprocessingml" in mime_type:
            text = self._extract_docx_text(content)
            return self.import_position_text(text, source_id=source_id)
        if lower_name.endswith((".csv", ".txt", ".tsv", ".md", ".json")) or mime_type.startswith("text/"):
            text = content.decode("utf-8-sig", errors="replace")
            return self.import_position_text(text, source_id=source_id)
        snapshot = self.get_snapshot()
        gaps = list(snapshot.get("gaps", []))
        gaps.append(f"{file_name} registered; OCR/parser not available yet")
        snapshot["gaps"] = gaps
        self._write_json(self.snapshot_path, snapshot)
        return snapshot

    def build_hand_payload(self) -> dict[str, Any]:
        snapshot = self.get_snapshot()
        top_positions = [
            {
                "ticker": p["ticker"],
                "market_value": p["market_value"],
                "weight": p["weight"],
                "unrealized_pnl": p["unrealized_pnl"],
                "unrealized_pnl_pct": p["unrealized_pnl_pct"],
            }
            for p in snapshot.get("positions", [])[:10]
        ]
        return {
            "source": "brain.portfolio_data_hub",
            "portfolio_summary": {
                "updated_at": snapshot.get("updated_at", ""),
                "position_count": snapshot.get("position_count", 0),
                "totals": snapshot.get("totals", {}),
                "risk_flags": snapshot.get("risk_flags", []),
                "watch_targets": snapshot.get("watch_targets", []),
            },
            "top_positions": top_positions,
            "gaps": snapshot.get("gaps", []),
        }

    def _parse_rows(self, text: str) -> list[dict[str, str]]:
        text = (text or "").strip()
        if not text:
            return []
        sample = text[:1024]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(StringIO(text), dialect=dialect))
        if rows and any(rows[0].keys()):
            return [{self._norm_key(k): (v or "").strip() for k, v in row.items()} for row in rows]
        parsed = []
        for line in text.splitlines():
            match = re.search(
                r"(?P<ticker>[A-Za-z]{1,6})\s+"
                r"(?P<quantity>-?\d+(?:\.\d+)?)"
                r"(?:.*?(?:cost|成本|avg)\s*\$?(?P<avg_cost>-?\d+(?:\.\d+)?))?"
                r"(?:.*?(?:price|现价|market)\s*\$?(?P<market_price>-?\d+(?:\.\d+)?))?",
                line,
                re.IGNORECASE,
            )
            if match:
                parsed.append({k: v or "" for k, v in match.groupdict().items()})
        return parsed

    def _row_to_position(self, row: dict[str, str], source_id: str) -> dict[str, Any] | None:
        ticker = (row.get("ticker") or row.get("symbol") or row.get("标的") or "").strip().upper()
        if not ticker:
            return None
        quantity = _num(row.get("quantity") or row.get("shares") or row.get("持仓") or row.get("数量"))
        avg_cost = _num(row.get("avg_cost") or row.get("cost") or row.get("成本") or row.get("cost_basis"))
        market_price = _num(row.get("market_price") or row.get("price") or row.get("现价") or row.get("last"))
        cost_basis = quantity * avg_cost if quantity is not None and avg_cost is not None else 0.0
        market_value = quantity * market_price if quantity is not None and market_price is not None else 0.0
        pnl = market_value - cost_basis if market_value or cost_basis else 0.0
        pnl_pct = pnl / cost_basis if cost_basis else 0.0
        return {
            "ticker": ticker,
            "quantity": quantity or 0.0,
            "avg_cost": avg_cost or 0.0,
            "market_price": market_price or 0.0,
            "cost_basis": round(cost_basis, 4),
            "market_value": round(market_value, 4),
            "unrealized_pnl": round(pnl, 4),
            "unrealized_pnl_pct": pnl_pct,
            "currency": (row.get("currency") or row.get("币种") or "USD").strip() or "USD",
            "source_id": source_id,
        }

    def _build_snapshot(self, positions: list[dict[str, Any]], source_id: str) -> dict[str, Any]:
        total_market = sum(p["market_value"] for p in positions)
        total_cost = sum(p["cost_basis"] for p in positions)
        for p in positions:
            p["weight"] = (p["market_value"] / total_market) if total_market else 0.0
        positions.sort(key=lambda p: p["market_value"], reverse=True)
        risk_flags = []
        gaps = []
        for p in positions:
            if p["weight"] > 0.2:
                risk_flags.append(f"{p['ticker']} weight exceeds 20%")
            if not p["market_price"]:
                gaps.append(f"{p['ticker']} missing market price")
            if not p["avg_cost"]:
                gaps.append(f"{p['ticker']} missing average cost")
        return {
            "snapshot_id": f"portfolio-{uuid.uuid4().hex[:8]}",
            "source_id": source_id,
            "updated_at": _now(),
            "position_count": len(positions),
            "positions": positions,
            "totals": {
                "market_value": round(total_market, 4),
                "cost_basis": round(total_cost, 4),
                "unrealized_pnl": round(total_market - total_cost, 4),
                "unrealized_pnl_pct": ((total_market - total_cost) / total_cost) if total_cost else 0.0,
            },
            "risk_flags": risk_flags,
            "gaps": gaps,
            "watch_targets": [p["ticker"] for p in positions],
        }

    def _public_source(self, source: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        has_secret = bool(secrets.get(source.get("id")))
        return {
            "id": source.get("id"),
            "type": source.get("type"),
            "name": source.get("name"),
            "status": "configured" if has_secret or source.get("status") == "configured" else source.get("status", "pending"),
            "config": source.get("config", {}),
            "auth": {"configured": has_secret},
            "created_at": source.get("created_at", ""),
            "updated_at": source.get("updated_at", ""),
        }

    @staticmethod
    def _public_config(data: dict[str, Any], source_type: str) -> dict[str, Any]:
        allowed = {
            "google_docs": ["document_id", "sheet_name", "sync_mode"],
            "notion": ["database_id", "page_id", "sync_mode"],
            "local_file": ["file_name", "mime_type"],
            "manual": ["label"],
        }.get(source_type, [])
        return {key: str(data[key]) for key in allowed if data.get(key)}

    @staticmethod
    def _extract_secret(data: dict[str, Any]) -> str:
        return str(data.get("api_token") or data.get("oauth_token") or data.get("access_token") or "").strip()

    @staticmethod
    def _source_id(data: dict[str, Any]) -> str:
        source_id = str(data.get("id") or "").strip()
        if source_id:
            return source_id
        base = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(data.get("name") or data.get("type") or "source")).strip("-")
        return (base or "source").lower()

    @staticmethod
    def _norm_key(key: str | None) -> str:
        key = (key or "").strip().lower()
        key = key.replace(" ", "_").replace("-", "_")
        return key

    @staticmethod
    def _extract_docx_text(content: bytes) -> str:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
        xml = re.sub(r"</w:t>\s*<w:t[^>]*>", "\n", xml)
        xml = re.sub(r"<[^>]+>", "", xml)
        return "\n".join(line.strip() for line in xml.splitlines() if line.strip())

    @staticmethod
    def _empty_snapshot() -> dict[str, Any]:
        return {
            "snapshot_id": "",
            "source_id": "",
            "updated_at": "",
            "position_count": 0,
            "positions": [],
            "totals": {"market_value": 0.0, "cost_basis": 0.0, "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0},
            "risk_flags": [],
            "gaps": [],
            "watch_targets": [],
        }

    @staticmethod
    def _read_json(path: Path, fallback: Any) -> Any:
        if not path.exists():
            return fallback
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return fallback

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _num(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
