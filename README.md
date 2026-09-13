# scg-wso2-management

把 **WSO2 APIM 4.7** Publisher 中已发布的 API，通过一个外部 Python **reconcile adapter**
对账下发到 **Spring Cloud Gateway 4.3** 与 **Higress** 两个数据面。

> 目标：在 Publisher 发布 2 个 API → SCG、Higress 两个网关都能路由（200）；
> 在 Publisher 下线 → 两个网关都收敛为 404。幂等、只纳管自有资源。

## 已验证（2026-09-13）

WSO2 APIM **4.7.0 从源码构建产物**本机运行（JDK21，offset=100，:9543），端到端：

| 阶段 | SCG :9080 | Higress :18080 |
|---|---|---|
| 发布 DemoEcho/DemoTime 后 `sync` | 200 / 200 | 200 / 200 |
| 「Demote to Created」后 `sync` | 404 / 404 | 404 / 404 |
| 重新 Publish 后 `sync` | 200 / 200 | 200 / 200 |

证据：[`evidence/task6-e2e-lifecycle.md`](evidence/task6-e2e-lifecycle.md)。

## 架构

```
WSO2 APIM 4.7 (Publisher v4 REST, DCR+OAuth)
        │ 轮询 PUBLISHED
        ▼
  adapter (Python)  → 统一模型 Route/Upstream
   ┌───────┴────────┐
   ▼                ▼
SCG 4.3         Higress/Envoy
Actuator 热写    标准 Ingress(docker cp / kubectl)
   └───────┬────────┘
           ▼
     downstream demo :9081
```

## 目录

- `adapter/` — 对账器：`wso2_client`（DCR/OAuth/读 API）、`model`（DTO→统一路由）、
  `state`（快照 diff）、`sinks/scg.py`、`sinks/higress.py`、`main`（diff/sync/loop）
- `infra/scg/` — SCG 4.3（Boot 3.5 / Spring Cloud 2025.0.3，纯动态路由工程）
- `infra/downstream/` — Python 演示上游（/demo/echo·time·headers:9081）
- `infra/wso2-apim/` — 源码、maven-settings、解压运行目录（大文件已 gitignore）
- `scripts/` — 02 发布 demo API、03 生命周期切换、源码产物启动脚本
- `docs/` — [PLAN](docs/PLAN.md)、[RUNBOOK](docs/RUNBOOK.md)、
  [TROUBLESHOOTING](docs/TROUBLESHOOTING.md)、3 份调研报告

## 快速开始

见 **[docs/RUNBOOK.md](docs/RUNBOOK.md)**。最短路径：

```bash
bash scripts/start-apim-from-build.sh                 # WSO2 :9543
(cd infra && docker compose up -d --build)            # SCG :9080 + downstream :9081
WSO2_PORT=9543 bash scripts/02-publish-demo-apis.sh    # Publisher 建 2 API 并发布
(cd adapter && PYTHONPATH=src python -m wso2_adapter.main --config config.local.yaml sync)
curl -s http://127.0.0.1:9080/demo/time                # 200
curl -s http://127.0.0.1:18080/demo/time              # 200 (Higress)
```

## 非目标（当前）

生产化（外部 DB、多节点、TLS、AMQP 准实时事件、认证透传/Key Manager 集成）；
本仓库聚焦证明「外部 adapter + Publisher REST 轮询对账」这条集成路径可行。
