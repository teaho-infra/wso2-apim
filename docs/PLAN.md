# SCG + Higress 双网关统一纳管（WSO2 APIM 控制面）实施计划

> 状态：**⏸️ v2，等待 review 后开工**
> 日期：2026-09-13
> 作者：Hermes（调研 + 规划）

## 目标（一句话）

在本机用 **WSO2 API Manager 4.7.0** 作为统一 API 控制面，通过一个自研 **adapter** 把 WSO2 Publisher 发布的 API 实时同步为 **Spring Cloud Gateway 4.2.x** 与 **Higress（现有 all-in-one 容器）** 两边的路由，并完成「发布 2 个 API → 双网关均可访问 → 删除后路由消失」的端到端验证；同时从 product-apim 源码完整构建一次 4.7.0 产物，具备二次开发能力。

## 架构（3 句话）

WSO2 APIM all-in-one（Docker）承担 API 设计/发布/生命周期管理，是唯一的 **Desired State 来源**；adapter（Python，独立进程）定时调用 Publisher REST v4 拉取已发布 API 做 **reconcile**，统一路由模型 `{name, path, methods, upstream}` 分别翻译成 SCG Actuator RouteDefinition 与 Higress 标准 Ingress；两种网关各自热加载，无需重启。事件触发（AMQP 订阅 WSO2 notification stream）作为第二阶段的实时性增强，不阻塞主链路。

### Scope（明确边界）

**IN**：① APIM 4.7 镜像实例跑通并 REST 自动发布 API；② 一个 Python adapter 把已发布 API  reconcile 到 SCG 4.2 + 现有 Higress；③ 发布/变更/下线全生命周期双网关验证；④ product-apim 4.7.0 源码完整构建一次并能启动（具备二开能力）。
**OUT（阶段二，见 §8）**：AMQP 实时事件、OSGi GatewayDeployer、WSO2 JWT/订阅鉴权打通、WSO2 自带网关数据面、限流/熔断策略映射。

> **关于「基于源码搭建」的执行顺序（重要决策点）**：先用官方镜像把 APIM 跑通（Task 1–6，约半天完成端到端闭环），源码构建放 Task 7。原因：源码构建官方数据缺失、预估 30–90 分钟且受 WSO2 私有 Maven 仓网络影响，放在最后不会阻塞主链路验证；源码产物验证通过后同样具备二开能力。若你要求「必须源码产物先跑、再做适配」，告知我，把 Task 7 提前为 Task 1。

## 技术栈

| 组件 | 版本/形态 | 说明 |
|---|---|---|
| WSO2 APIM | **4.7.0 GA**（2026-04-29） | 先官方镜像 `wso2/wso2am:4.7.0-alpine` 跑通；后源码构建 |
| 源码构建 JDK | Temurin **21** + Maven 3.8.2 | 4.7 运行要求 JDK 21；官方构建文档 JDK11/21 口径矛盾，默认 21 |
| Spring Cloud Gateway | **4.2.x**（Spring Cloud 2024.0.x / Boot 3.4 / JDK 17） | 新建独立容器，开启 actuator gateway 写端点 |
| Higress | 现有 all-in-one 容器（已在运行） | console :18001 / 网关 :18080 / apiserver :18443 |
| downstream | 复用已有镜像 `downstream-service:latest`（不足则补 python echo） | 演示上游 |
| adapter | Python 3.11 + httpx + pyyaml | 无框架，CLI + reconcile loop |

---

## §1 环境审计（2026-09-13 实测）

| 项 | 现状 | 是否满足 | 处理 |
|---|---|---|---|
| JDK | 8/11/17/21 均装 | ✅ | 运行用 21，SCG 用 17 |
| Maven | `~/soft/maven/apache-maven-3.8.2` | ✅ | 构建时指定 settings.xml（保留 wso2 nexus） |
| Node | v24.12 | ✅（构建 product-apim 不需要，仅 apim-apps 才需 22+） | — |
| Docker | 29.2.1 + compose v5 | ✅ | — |
| 内存/磁盘 | 46G（23G 可用）/ 369G | ✅ | APIM 建议 4G，给容器限 4G 堆 |
| 代理 | mihomo `127.0.0.1:7890` | ✅ | 容器走 host 代理或镜像加速 |
| 镜像拉取 | `wso2/wso2am:4.7.0-alpine` manifest 实测可访问 | ✅ | 若 Docker Hub 超时，换 release zip 直链 |
| Higress | all-in-one 容器 `higress` Up，:18001 console 返回 200、:18080 网关 200 | ✅ | 复用，不新起 |
| 旧资产 | `agentspace/scg-to-higress-migration` 有 SCG 3.1.2 项目、`migrate.py`（SCG 路由→Ingress 转换器）、`downstream-service:latest` 镜像、`/data` docker cp 推送法 | ✅ 参考/复用 | adapter 的 Higress sink 直接借鉴其 Ingress/Service/Endpoints 模板 |
| sudo | 非常驻，偶发可请用户执行 | 🟡 | 全部走用户态 + Docker，不要求 sudo |

### 端口分配（已核对 `ss -ltn`，9443/8243/8280/5672/9711 全空闲）

| 端口 | 服务 | 备注 |
|---|---|---|
| 9443 | WSO2 APIM console/publisher/devportal/carbon (https) | 核心管理口 |
| 9763 | WSO2 APIM http | 仅排障用 |
| 8243/8280 | WSO2 自带网关 https/http | 验证时**不经过它**（我们纳管的是外部 SCG/Higress） |
| 5672 | WSO2 AMQP broker | 阶段二 adapter 实时事件用 |
| 9711/9611/10389/9099 | TM/ldap/management | 容器内用，宿主不必映射 |
| **9080** | SCG 实例（http + actuator） | 新增 |
| **9081** | downstream 演示服务 | 新增 |
| 18001/18080/18443 | Higress（已占用，保持） | 不碰 |

## §2 架构设计

```
                          ┌──────────────────────────────┐
                          │  WSO2 APIM 4.7 (docker)       │
   浏览器 ── :9443 ───────▶│  Publisher / DevPortal / TM   │
                          │  Publisher REST v4 :9443      │── :5672 AMQP(阶段二)
                          └──────────────┬───────────────┘
                                         │ ① GET /apis?lifecyclestatus=PUBLISHED
                                         │   GET /apis/{id} (endpointConfig/policies)
                                         ▼
                          ┌──────────────────────────────┐
                          │  adapter (Python)             │
                          │  wso2_client → model(统一模型) │
                          │  reconcile: desired vs cached │
                          └───────────┬──────────────┬────┘
              ② POST /actuator/gateway/routes/{id}   ③ Ingress+Svc+EP
                 + POST /refresh (亚秒生效)          （kubeconfig apply 优先；
                       │                             docker cp /data 兜底）
                       ▼                                     ▼
        ┌───────────────────────────┐        ┌──────────────────────────┐
        │ SCG 4.2 容器 :9080         │        │ Higress all-in-one        │
        │ (actuator 写端点开启)      │        │ controller→pilot→xDS→envoy│
        └─────────────┬─────────────┘        └────────────┬─────────────┘
                      │  /demo/echo, /demo/time 转发       │
                      └──────────────┬─────────────────────┘
                                     ▼
                          ┌──────────────────────────────┐
                          │ downstream :9081              │
                          │ (/demo/echo, /demo/time)      │
                          └──────────────────────────────┘
```

**流量路径**
- Path A（管理面）：人/脚本 → WSO2 Publisher REST 创建并 Publish API。
- Path B（同步面）：adapter 周期 reconcile（默认 10s）→ 双网关热更新。
- Path C（数据面验证）：curl → SCG:9080 或 Higress:18080 → downstream。
- Path D（阶段二实时）：adapter 订阅 AMQP notification stream → 立即触发 reconcile。

### 关键设计决策（来自调研，含已排除方案）

1. **选方案 B（外部 adapter 服务）而非 OSGi GatewayDeployer**：与 APIM 进程解耦、语言无关、适配 4.x 全版本、不背 OSGi 升级包袱；一个组件统一双网关。OSGi 方案记为后续增强（见 §8）。
2. **reconcile 优先于事件订阅**：AMQP notification 负载是内部 DTO、无公开稳定承诺；以 REST 拉取 + 本地状态对账为主链路（幂等、可重放、可审计），AMQP 只做"提前唤醒"。
3. **不裸写 Higress Nacos dataId**：格式未公开。走标准 K8s Ingress（`ingressClassName: higress`），通道三选一实测选定。
4. **SCG 用独立 4.2.x 新实例**，不改造旧迁移项目的 3.1.2（Boot2/Consul/Sentinel 耦合重）；旧项目的 `migrate.py` Ingress 模板与 downstream 镜像复用。
5. **WSO2 自带网关不作为数据面**：它照常启动（all-in-one 不可拆），但验证流量只打 SCG/Higress，避免概念混淆。

### 统一路由模型（adapter 内部）

```json
{
  "apiId": "uuid",
  "name": "demo-echo-api",
  "context": "/demo/echo",
  "version": "1.0.0",
  "methods": ["GET"],
  "upstream": {"host": "downstream", "port": 9081, "protocol": "http"},
  "revision": "wso42-rev"
}
```

WSO2 侧约定（让模型可确定翻译）：API context 即网关 path（`/demo/echo`），endpoint 指向 downstream `http://downstream:9081`，HTTP_METHODS 限流策略携带方法集；adapter 不做路径改写（StripPrefix=0），保持两网关行为一致。

## §3 目录结构（目标态）

```
scg-wso2-management/
├── README.md                         # 5 分钟快速跑 + 架构
├── docs/
│   ├── PLAN.md                       # 本文件
│   ├── RESEARCH-WSO2-APIM-BUILD.md   # 调研①：源码构建/运行/镜像
│   ├── RESEARCH-WSO2-FEDERATION.md   # 调研②：联邦网关/扩展点
│   ├── RESEARCH-GATEWAY-ROUTING.md   # 调研③：SCG/Higress 动态路由
│   ├── ARCHITECTURE.md               # 阶段末补：决策记录 + 时序
│   └── TROUBLESHOOTING.md            # 踩坑清单
├── infra/
│   ├── wso2-apim/
│   │   ├── docker-compose.yml        # 镜像形态（主用）
│   │   ├── config/deployment.toml    # 挂载覆盖（端口/内存，必要时）
│   │   └── source/                   # .gitignore：product-apim 源码
│   ├── scg/
│   │   ├── Dockerfile                # JDK17 + fatjar
│   │   ├── pom.xml
│   │   └── src/main/resources/application.yml
│   ├── downstream/
│   │   ├── Dockerfile (python http, 仅当旧镜像不够用)
│   ├── higress/
│   │   └── README.md                 # 对接现有容器：三通道、kubeconfig
│   └── docker-compose.yml            # SCG + downstream 两个服务
├── adapter/
│   ├── requirements.txt
│   ├── config.example.yaml
│   └── src/wso2_adapter/
│       ├── __init__.py / main.py     # CLI: sync once / loop / diff
│       ├── wso2_client.py            # DCR + OAuth + Publisher v4
│       ├── model.py                  # 统一模型 + WSO2 DTO 翻译
│       ├── state.py                  # 本地 desired cache (json)
│       └── sinks/
│           ├── scg.py                # actuator routes CRUD + refresh
│           ├── higress.py            # ingress 渲染 + 三通道投递
│           └── templates/            # ingress/service/endpoints yaml
├── scripts/
│   ├── 01-start-apim.sh
│   ├── 02-publish-demo-apis.sh       # REST 建 2 个 API 并 Publish
│   ├── 03-start-gateways.sh
│   ├── 04-reconcile.sh
│   ├── 05-verify-e2e.sh
│   └── 10-build-apim-from-source.sh  # 源码构建
└── evidence/                         # curl 输出、截图式日志（提交）
```

## §4 任务分解（每任务一 commit，15–40 分钟）

### Task 1 — WSO2 APIM 4.7 镜像形态启动 + 健康验证
**目标**：:9443 可登录，REST 可通；同时后台开始 clone 源码（为 Task 7 预热）。

**Files**：`infra/wso2-apim/docker-compose.yml`、`scripts/01-start-apim.sh`
**Steps**：
1. 写 compose：image `wso2/wso2am:4.7.0-alpine`，映射 9443/9763/8243/8280/5672，`JVM_MEM_OPTS=-Xms512m -Xmx2048m`，容器网络加入能解析 downstream 的同一 compose 网络（或 host 网络别名）。
2. `docker compose up -d`，轮询 `https://127.0.0.1:9443/carbon` 与 `/services/Version` 直到 200（首次 1–3 分钟）。
3. admin/admin 登录 carbon 验证；记录首次是否强制改密（若强制，脚本中预置 offset 或手工改后记入 .env.local）。
4. 后台：`git clone --branch v4.7.0 --depth 1 https://github.com/wso2/product-apim`（git 协议若超时改用 codeload tarball）。
**验证**：
```bash
curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1:9443/carbon/admin/login.jsp   # 200
docker logs <apim> | grep -i 'started' | head
```
**Commit**：`infra(wso2): add apim 4.7 compose and start script`

### Task 2 — Publisher REST v4 打通 + 自动发布 2 个演示 API
**目标**：纯脚本完成 DCR 注册 → OAuth token → 建 API → Publish，不手点 UI。

**Files**：`scripts/02-publish-demo-apis.sh`、`infra/wso2-apim/demo-api-echo.json`、`demo-api-time.json`
**Steps**：
1. DCR：`POST /client-registration/v0.17/register`（basic admin:admin）拿 clientId/secret（缓存复用）。
2. `POST /oauth2/token` password grant（admin/admin，scope=`apim:api_create apim:api_publish apim:api_view`）。
3. `POST /api/am/publisher/v4/apis` 建 2 个 API：
   - `demo-echo-api` v1.0.0，context `/demo/echo`，endpoint `http://downstream:9081`（docker 网络名；若 APIM 容器无法解析则用宿主 IP，需在计划执行时实测选定并记录）
   - `demo-time-api` v1.0.0，context `/demo/time`
4. 补必填：business information 可跳过；policies 设 `Unlimited`；`POST /apis/{id}/lifecycle?action=Publish`。
5. `GET /apis?lifecyclestatus=PUBLISHED` 确认 2 条。
**验证**：脚本输出 2 个 apiId 且 GET 列表 count=2；浏览器 Publisher 门户见 PUBLISHED。
**Commit**：`feat(wso2): scripted DCR, api creation and publish for 2 demo apis`
**风险**：v4 DTO 必填字段（operations/policies/endpointSecurity）首次试跑会 400，按报错补齐，把最终可用 JSON 存档。

### Task 3 — downstream + SCG 4.2 容器，手工验证 actuator 热写路由
**Files**：`infra/docker-compose.yml`、`infra/scg/{Dockerfile,pom.xml,application.yml}`、`scripts/03-start-gateways.sh`
**Steps**：
1. downstream：优先复用 `downstream-service:latest`（确认其路径含 `/demo/echo`；若不含则补一个 python:3.11-slim 小服务，提供 `/demo/echo` 返回 JSON、`/demo/time` 返回时间）。
2. SCG 4.2 工程（Boot 3.4 / JDK17 / Java 17 bytecode）：**注意 4.2 起 artifact 改名**，依赖用 `spring-cloud-starter-gateway-server-webflux`（4.1 及以前才是 `spring-cloud-starter-gateway`）+ `spring-boot-starter-actuator`；`application.yml`：
   ```yaml
   server.port: 9080
   management.endpoints.web.exposure.include: gateway,health
   management.endpoint.gateway.access: unrestricted
   ```
3. 构建 fatjar → 镜像 → compose 起 :9080。
4. 手工 `POST /actuator/gateway/routes/demo-manual`（Path=/demo/echo/**, uri=http://downstream:9081）→ `POST /actuator/gateway/refresh` → `GET /actuator/gateway/routes` 看到 → `curl :9080/demo/echo` 200 → DELETE + refresh 验证消失。
**验证**：上述 curl 全通，记录响应到 `evidence/task3-scg-actuator.txt`。
**Commit**：`infra(scg): scg 4.2 with writable actuator and downstream service`

### Task 4 — adapter 骨架 + SCG sink + reconcile dry-run
**Files**：`adapter/`（requirements.txt、wso2_client/model/state/sinks/scg.py、main.py）
**Steps**：
1. `wso2_client.py`：封装 Task 2 的 token/建 API 查询（只做读：list published + get detail）。
2. `model.py`：API DTO → 统一模型；`state.py`：`evidence/state.json` 存上次 desired。
3. `sinks/scg.py`：diff → DELETE 旧的/POST 新的（更新=先删后建，避免重复 POST 同 id 的坑）→ refresh；幂等。
4. `main.py sync --sink scg --dry-run` 先打印计划，去掉 dry-run 实际下发。
**验证**：`curl :9080/demo/echo` 与 `/demo/time` 均 200；`GET /actuator/gateway/routes` 正好 2 条 adapter 管的（manual 的不动）。
**Commit**：`feat(adapter): wso2 source and scg actuator sink with reconcile`

### Task 5 — Higress sink：三通道探测选优并打通
**Files**：`adapter/src/wso2_adapter/sinks/higress.py`、`templates/*.yaml`、`infra/higress/README.md`
**Steps**（按此顺序探测，第一个通的即定为通道，其余记录）：
1. **通道① kubeconfig apply**：容器 kubeconfig 指向 https://localhost:18443，实测现为 basic-auth 弹窗；试 kubeconfig 内填 admin/admin（试 `admin/admin`、`admin/higress`）后 `kubectl apply` Ingress+Service+Endpoints（namespace `higress-system`，ingressClassName `higress`）。
2. **通道② docker cp**（旧项目已验证）：渲染 `ingresses/`、`services/`、`endpoints/` yaml → `docker cp` 进 `higress:/data/<type>/`（Endpoints 指向宿主 docker 网桥 IP:9081，同旧 migrate.py 的 host_ip 做法）。
3. **通道③ Console REST**：在 :18001 的 swagger/js 里定位真实登录路径（非 /v1/auth/login，候选 /v1/session/login），拿 cookie 后 `POST /v1/routes`。
4. Higress 侧 path 与 SCG 完全一致（`/demo/echo` Prefix → downstream service）；method 限制首期靠 annotations（若该 Higress 版本注解不支持则记录降级为不限 method）。
**验证**：`curl :18080/demo/echo`、`/demo/time` 200；console 路由列表可见；证据入 `evidence/task5-higress.txt`。
**Commit**：`feat(adapter): higress ingress sink via <选定通道>`

### Task 6 — 端到端闭环 + 增删变更全场景 + 证据
**Files**：`scripts/04-reconcile.sh`、`05-verify-e2e.sh`、`evidence/*`、`README.md`、`docs/ARCHITECTURE.md`
**Steps**：
1. 新增：跑 Task 2 脚本建 2 API → `adapter sync`（双 sink）→ 四组 curl（SCG×2、Higress×2）全 200。
2. 变更：WSO2 里新建第 3 个 API `/demo/headers` → 再 sync → 两网关各 3 条，旧路由不抖。
3. 删除：WSO2 里把 `/demo/time` 下线（Lifecycle Deprecated→Retired 或直接删除）→ sync → 两网关该路由 404，其余仍 200。
4. 幂等：连跑 3 次 sync，路由表无变化、无重复（SCG 无 500、Higress 无重复 ingress）。
5. `05-verify-e2e.sh` 一把跑完并把输出存 `evidence/e2e-<时间戳>.log`。
**Commit**：`test(e2e): publish/sync/retire lifecycle across scg and higress`

### Task 7 — product-apim 4.7.0 源码构建
**Files**：`scripts/10-build-apim-from-source.sh`、`docs/TROUBLESHOOTING.md`
**Steps**：
1. `source/` 下 clone tag `v4.7.0`（或解压 codeload zip）。
2. 用 JDK21 + Maven 3.8.2，settings.xml 保留 `maven.wso2.org`（阿里云镜像缺 WSO2 构件），`MAVEN_OPTS=-Xmx4g`。
3. `mvn clean install -Dmaven.test.skip=true`；产物 `all-in-one-apim/modules/distribution/product/target/wso2am-4.7.0.zip`（4.7 新路径）。
4. 记录构建墙钟时长、失败模块与解法（若 JDK21 有怪问题，降到 JDK17 重试并记录官方口径矛盾）。
5. 解压产物到 `infra/wso2-apim/runtime/`（gitignore）。改端口启动到 **9543** 避让 docker 版：WSO2 不支持直接改启动端口，需在 `conf/deployment.toml` 设 `[server]\noffset = 100`（全端口 +100：9443→9543、8243→8343…），再 `bin/api-manager.sh` 启动，验证 :9543/carbon 200，证明"源码可改可跑"。与 docker 版不并存长期运行（验证后停掉其一）。
**验证**：zip 存在且大小合理；源码版 :9543 carbon 200；构建日志摘要入 evidence。
**Commit**：`build(wso2): verified source build of product-apim 4.7.0 (jdk21)`
**风险/降级**：若私有仓依赖拉取超 90 分钟仍失败，记录失败点，保留 docker 形态为主链路，源码构建标 ❌ 并在 README 说明——不阻塞 Task 1–6 成果。

### Task 8 — 收尾文档 + 提交（推送按需）
**Files**：`README.md`（快速跑/架构/验证矩阵 ✅🟡❌/踩坑）、`docs/TROUBLESHOOTING.md`
**Steps**：整理 commits；确认 `.gitignore` 排除 runtime/source/*.zip/state；用户确认后再建 GitHub private repo 推送（**不自动推**）。

## §5 验证计划

| 阶段 | 验证项 | 命令 | 通过标准 |
|---|---|---|---|
| T1 | APIM 就绪 | `curl -sk :9443/carbon/admin/login.jsp` | 200 |
| T2 | 2 API PUBLISHED | publisher REST list | count=2 |
| T3 | SCG 热写 | actuator POST→refresh→curl | 200 后可 DELETE 消失 |
| T4 | adapter→SCG | `curl :9080/demo/{echo,time}` | 均 200，routes=2 |
| T5 | adapter→Higress | `curl :18080/demo/{echo,time}` | 均 200 |
| T6 | 增/删/幂等 | `05-verify-e2e.sh` | 新增同步、Retire 后 404、连跑 3 次无 diff |
| T7 | 源码构建 | zip + :9543 | 产物存在、carbon 200（或明确降级记录） |

## §6 风险与权衡

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | WSO2 v4 API DTO 必填项多，脚本建 API 易 400 | 中 | Task 2 预留试错，最终 JSON 存档；也可改走 `/apis/import-openapi` |
| R2 | 网关→downstream 网络可达性 | 中 | 先澄清一点：**APIM 容器不需要能连 downstream**——endpointConfig 只是声明值，adapter 读取后由 SCG/Higress 转发。SCG↔downstream 同在本项目 compose 网络用服务名；Higress 是已存在的独立容器，Endpoints 用宿主 docker 网桥 IP（旧项目已验证） |
| R3 | Higress 18443 basic-auth 凭据未知 / console 登录路径变 | 中 | 三通道兜底，docker cp 已被旧项目证明可行，不会卡死 |
| R4 | Higress 该版本 method 级路由注解不支持 | 低 | 首期不限 method，文档标 🟡；或用 HTTPRoute CRD |
| R5 | WSO2 AMQP 1.0/0-9-1 协议与 Python 客户端兼容 | 低 | 阶段二事项；主链路不依赖 |
| R6 | 4.7 源码构建 JDK 口径矛盾、依赖巨大 | 中 | JDK21→17 降级重试；设 90 分钟预算；失败不阻塞主链路 |
| R7 | 4G 堆 APIM + IDE 等抢内存 | 低 | 限 2G 堆、必要时停 multica 之外的非必要容器 |
| R8 | adapter 直连 WSO2 用 admin 凭据 | 低（本机实验） | 支持 config.yaml/env 注入，不入库；README 注明生产须用 service provider 最小 scope |

## §7 与既有项目的关系

- **复用**：`agentspace/scg-to-higress-migration/scripts/migrate.py` 的 Ingress/Service/Endpoints 渲染逻辑、其踩坑结论（Service port name 必须与 Endpoints 对齐、host IP Endpoints、等待 35s xDS 生效）、`downstream-service:latest` 镜像。
- **不修改**旧项目；本项目自包含。
- multica 占用 3000/8090、旧 demo 占 8080、Himarket/Nacos 占 15173/15174/18081/19080/8849 等——端口表已全部避让。

## §8 阶段二（本次不做，留口）

1. AMQP 订阅 `org.wso2.apimgt.notification.stream` 触发即时 reconcile（Python 客户端协议待验证）。
2. OSGi `GatewayDeployer` 自定义网关 Agent（方案 A），让 Deployments UI 直接反映 SCG/Higress 下发成败。
3. 鉴权对齐：WSO2 KM 签发 JWT → SCG 自定 JWT filter / Higress key-auth/consumer，验证订阅级 key 流转。
4. Higress 侧 method/限流/鉴权策略映射；Gateway API HTTPRoute 替代 Ingress。

## §9 执行节奏（检查点）

- **CP1（T2 后）**：WSO2 控制面可用、API 已发布——可停下 review。
- **CP2（T5 后）**：单 adapter 双网关下发通——核心目标达成，可 review。
- **CP3（T6 后）**：完整生命周期闭环 + 证据——主交付完成。
- **CP4（T7 后）**：源码构建完成，项目收尾、按需推送 GitHub。
