"""本地期望状态快照(desired state cache),用于 reconcile diff。"""
from __future__ import annotations

import json
from pathlib import Path

from .model import Route


class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.routes: dict[str, Route] = {}

    def load(self) -> dict[str, Route]:
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            for item in raw.get("routes", []):
                up = item.get("upstream")
                from .model import Upstream
                self.routes[item["name"]] = Route(
                    api_id=item["api_id"], name=item["name"], path=item["path"],
                    methods=item.get("methods", []),
                    upstream=Upstream(**up) if up else None,
                    revision=item.get("revision", ""),
                )
        return self.routes

    def save(self, routes: dict[str, Route]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"routes": [r.to_dict() for r in routes.values()]},
            ensure_ascii=False, indent=2,
        ))
        self.routes = routes
