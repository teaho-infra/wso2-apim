# Task 6 — 端到端生命周期验证证据

日期：2026-09-13
环境：WSO2 APIM 4.7.0（源码构建产物，offset=100，管理口 https://127.0.0.1:9543）
数据面：SCG 4.3（容器 :9080）、Higress all-in-one（:18080）、downstream（容器 :9081）

## 链路

WSO2 Publisher（DemoEchoAPI `/demo/echo`、DemoTimeAPI `/demo/time`，PUBLISHED）
→ `python -m wso2_adapter.main sync`（DCR/OAuth → 读 Publisher v4 → 统一模型 → 双 sink reconcile）
→ SCG Actuator 热写 + Higress 标准 Ingress（docker cp 通道）

## 结果矩阵

| 阶段 | 操作 | SCG /demo/echo | SCG /demo/time | Higress /demo/echo | Higress /demo/time |
|---|---|---|---|---|---|
| 发布 | 2 API PUBLISHED + sync | **200** | **200** | **200** | **200** |
| 下线 | 2 API「Demote to Created」+ sync | **404** | **404** | **404** | **404** |
| 恢复 | 2 API「Publish」+ sync | **200** | **200** | **200** | **200** |

## reconcile 报告（实测）

- 发布态 sync：SCG `created=[wso2-demo-echo, wso2-demo-time]`；Higress `applied=[wso2-demo-echo, wso2-demo-time]`，host_ip=172.17.0.1
- 下线态 sync：`synced 0 routes`；SCG `deleted=[wso2-demo-echo, wso2-demo-time]`；Higress `deleted=[wso2-demo-echo.yaml, wso2-demo-time.yaml]`
- 恢复态 sync：两网关重新 created/applied，四路径回到 200
- 稳定态 `diff`：`desired=2 previous=2`，无 NEW/REMOVED/CHANGED（增删检测无漂移）
- 幂等：重复 sync 后 SCG 路由集合恒为 2 条 `wso2-demo-*`；Higress `/data/ingresses` 恒为 `default.yaml` + 2 条 `wso2-demo-*`，无重复/残留

## 只纳管自有资源

- SCG 仅增删带 `wso2-` 前缀的路由 id；人工/静态路由不触碰。
- Higress 仅增删带 `wso2-` 前缀的 Ingress；系统 `default.yaml`、`higress-gateway` Service 不触碰。

机器可读原始结果：`task6-e2e-lifecycle.json`
