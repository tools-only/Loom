"""Local domain manifest loading for Loom Core."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_domain_manifests(root_dir: str | Path) -> list[dict[str, Any]]:
    domains_dir = Path(root_dir) / "domains"
    if not domains_dir.exists():
        return []

    manifests: list[dict[str, Any]] = []
    for child in sorted(domains_dir.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest["manifest_path"] = str(manifest_path)
        manifests.append(manifest)
    return manifests


def build_domain_manifest_response(
    manifests: list[dict[str, Any]],
) -> dict[str, Any]:
    public_manifests = []
    for manifest in manifests:
        public_manifest = dict(manifest)
        public_manifest.pop("manifest_path", None)
        public_manifests.append(public_manifest)
    return {"ok": True, "domains": public_manifests}
