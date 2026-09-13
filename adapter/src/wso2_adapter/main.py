"""adapter CLI:从 WSO2 拉已发布 API → 统一模型 → 双网关 reconcile。

用法:
  python -m wso2_adapter.main --config config.local.yaml diff
  python -m wso2_adapter.main --config config.local.yaml sync            # 一次
  python -m wso2_adapter.main --config config.local.yaml loop            # 周期轮询
  python -m wso2_adapter.main --config config.local.yaml sync --sink scg # 只下发一个
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

from .model import route_from_wso2_api
from .state import StateStore
from .wso2_client import Wso2Client


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def build_desired(cfg: dict) -> dict:
    cache = str(Path(cfg.get("_config_dir", ".")) / ".wso2-cache.json")
    client = Wso2Client(cfg["wso2"], cache_path=cache)
    client.login()
    apis = client.list_published_apis()
    desired = {}
    for summary in apis:
        detail = client.get_api_detail(summary["id"])
        route = route_from_wso2_api(detail, cfg["wso2"].get("default_upstream", {}))
        desired[route.name] = route
    return desired


def cmd_diff(cfg: dict) -> int:
    desired = build_desired(cfg)
    store = StateStore(cfg["state_file"])
    previous = store.load()
    new = set(desired) - set(previous)
    gone = set(previous) - set(desired)
    changed = {n for n in set(desired) & set(previous)
               if desired[n].revision != previous[n].revision}
    print(f"desired={len(desired)} previous={len(previous)}")
    for label, items in (("NEW", new), ("REMOVED", gone), ("CHANGED", changed)):
        for n in sorted(items):
            r = desired.get(n) or previous.get(n)
            print(f"  {label:8s} {n:20s} {r.path if r else ''}")
    return 0


def cmd_sync(cfg: dict, only_sink: str | None = None) -> int:
    desired = build_desired(cfg)
    store = StateStore(cfg["state_file"])
    store.load()

    sink_reports = {}
    if cfg.get("scg", {}).get("enabled", True) and only_sink in (None, "scg"):
        from .sinks.scg import ScgSink
        sink_reports["scg"] = ScgSink(cfg["scg"]).reconcile(desired)
    if cfg.get("higress", {}).get("enabled", True) and only_sink in (None, "higress"):
        from .sinks.higress import HigressSink
        sink_reports["higress"] = HigressSink(cfg["higress"]).reconcile(desired)

    store.save(desired)
    print(f"synced {len(desired)} routes")
    for sink, rep in sink_reports.items():
        print(f"  [{sink}] {rep}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="WSO2 → SCG/Higress adapter")
    ap.add_argument("--config", default="config.local.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diff")
    sync_p = sub.add_parser("sync")
    sync_p.add_argument("--sink", choices=["scg", "higress"], default=None)
    sub.add_parser("loop")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    cfg["_config_dir"] = str(Path(args.config).resolve().parent)
    # state_file 相对配置目录
    if not Path(cfg["state_file"]).is_absolute():
        cfg["state_file"] = str(Path(cfg["_config_dir"]) / cfg["state_file"])

    if args.cmd == "diff":
        return cmd_diff(cfg)
    if args.cmd == "sync":
        return cmd_sync(cfg, args.sink)
    if args.cmd == "loop":
        interval = int(cfg.get("poll_interval_seconds", 10))
        while True:
            try:
                cmd_sync(cfg)
            except Exception as exc:  # noqa: BLE001
                print(f"[loop] error: {exc}", file=sys.stderr)
            time.sleep(interval)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
