"""统一路由模型:WSO2 API → 双网关无关的中间表示。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any
import json


@dataclass
class Upstream:
    host: str
    port: int
    protocol: str = "http"

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"


@dataclass
class Route:
    """一条被纳管的路由(对应一个 WSO2 published API)。"""

    api_id: str
    name: str           # 规范化后的短名,用作 SCG route id / ingress name
    path: str           # 网关匹配路径,如 /demo/echo(自动补 /**)
    methods: list[str] = field(default_factory=list)
    upstream: Upstream | None = None
    revision: str = ""  # WSO2 侧 revision/更新时间,用于变更检测

    @property
    def scg_path_pattern(self) -> str:
        # SCG Path predicate:/demo/echo 及其子路径
        return self.path.rstrip("/") + "/**"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _slugify(context: str) -> str:
    # /demo/echo --&gt; demo-echo
    return "-".join(p for p in context.strip("/").split("/") if p).lower()


def route_from_wso2_api(api: dict, default_upstream: dict) -> Route:
    """把 Publisher v4 API DTO 翻译成统一 Route。

    依赖字段(实测后可能微调):
      api.id, api.name, api.context, api.version,
      api.endpointConfig(JSON 字符串,含 production_endpoints),
      api.operations[].verb
    """
    context = api.get("context") or f"/{api.get('name','api')}"
    name = _slugify(context)

    # 方法:从 operations 收集
    methods = sorted({
        (op.get("verb") or "GET").upper()
        for op in (api.get("operations") or [])
        if op.get("verb")
    })

    # 上游:解析 endpointConfig
    upstream = _parse_endpoint(api.get("endpointConfig"), default_upstream)

    return Route(
        api_id=api["id"],
        name=name,
        path=context.rstrip("/"),
        methods=methods,
        upstream=upstream,
        revision=str(api.get("revisionId") or api.get("updatedAt") or api["id"]),
    )


def _parse_endpoint(raw: Any, default: dict) -> Upstream:
    """WSO2 endpointConfig 是 JSON 字符串。

    典型: {"endpoint_type":"http","production_endpoints":{"sandbox_default":"http://host:port"}}
    不同版本键名略有差异,做多键兜底。
    """
    cfg = {}
    if isinstance(raw, str) and raw.strip():
        try:
            cfg = json.loads(raw)
        except json.JSONDecodeError:
            cfg = {}
    elif isinstance(raw, dict):
        cfg = raw

    url = None
    pe = cfg.get("production_endpoints") or {}
    if isinstance(pe, dict):
        for key in ("sandbox_default", "default", "url"):
            if pe.get(key):
                url = pe[key]
                break
    if not url:
        url = cfg.get("url")

    if url and "://" in url:
        proto, rest = url.split("://", 1)
        host_port = rest.split("/", 1)[0]
        if ":" in host_port:
            host, port = host_port.rsplit(":", 1)
            return Upstream(host=host, port=int(port), protocol=proto)
        return Upstream(host=host_port, port=443 if proto == "https" else 80, protocol=proto)

    return Upstream(
        host=default["host"],
        port=int(default["port"]),
        protocol=default.get("protocol", "http"),
    )
