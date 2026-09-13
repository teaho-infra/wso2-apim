"""SCG sink:把统一 Route 热写到 Spring Cloud Gateway Actuator。

约束(调研实证):
  - 更新须先 DELETE 再 POST(重复 POST 同 id 会导致 GET 500)
  - POST/DELETE 后必须 POST /refresh 才生效
  - 只管理带 route_prefix 的路由,绝不删除人工/静态路由
"""
from __future__ import annotations

import httpx

from ..model import Route


class ScgSink:
    def __init__(self, cfg: dict):
        base = cfg["actuator_url"].rstrip("/")
        self.routes_url = base + "/routes"
        self.refresh_url = base + "/refresh"
        self.prefix = cfg.get("route_prefix", "wso2-")

    def _rid(self, name: str) -> str:
        return f"{self.prefix}{name}"

    def reconcile(self, desired: dict[str, Route]) -> dict:
        report = {"created": [], "updated": [], "deleted": [], "unchanged": []}
        existing = self._list_route_ids()
        managed_existing = {r for r in existing if r.startswith(self.prefix)}

        desired_ids = {self._rid(n) for n in desired}

        to_delete = managed_existing - desired_ids
        for rid in sorted(to_delete):
            self._delete(rid)
            report["deleted"].append(rid)

        for name, route in desired.items():
            rid = self._rid(name)
            if rid in managed_existing:
                # 先删后建,保证幂等
                self._delete(rid)
                self._post(rid, route)
                report["updated"].append(rid)
            else:
                self._post(rid, route)
                report["created"].append(rid)

        if report["created"] or report["updated"] or report["deleted"]:
            self._refresh()
        else:
            report["unchanged"] = sorted(desired_ids)
        return report

    def _list_route_ids(self) -> set[str]:
        r = httpx.get(self.routes_url, timeout=15)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            return set(data.keys())
        if isinstance(data, list):
            return {item.get("route_id") or item.get("routeId") for item in data}
        return set()

    def _post(self, rid: str, route: Route) -> None:
        predicates = [f"Path={route.scg_path_pattern}"]
        if route.methods:
            predicates.append("Method=" + ",".join(route.methods))
        body = {
            "predicates": predicates,
            "filters": [],
            "uri": route.upstream.url if route.upstream else "http://downstream:9081",
            "order": 0,
            "metadata": {"managed-by": "wso2-adapter", "api-id": route.api_id},
        }
        r = httpx.post(f"{self.routes_url}/{rid}", json=body, timeout=15)
        r.raise_for_status()

    def _delete(self, rid: str) -> None:
        r = httpx.delete(f"{self.routes_url}/{rid}", timeout=15)
        if r.status_code not in (200, 404):
            r.raise_for_status()

    def _refresh(self) -> None:
        r = httpx.post(self.refresh_url, timeout=15)
        r.raise_for_status()
