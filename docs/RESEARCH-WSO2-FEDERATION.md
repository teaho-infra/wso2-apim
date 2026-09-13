# WSO2 APIM 4.x 对接非 WSO2 网关调研报告

## 核心结论
**可行,且 4.6+ 已官方支持**。WSO2 APIM 4.6/4.7 引入 **Federated Gateways(联邦网关)** 架构,内置 AWS / Azure / **Kong** / **Envoy Gateway** 连接器,并提供官方 **Custom Gateway Agent 扩展点**(Java OSGi bundle,实现 `GatewayDeployer` 接口)。对 SCG 和 Higress,最现实的路径是:写自定义 Gateway Agent(进程内同步调用),或外部服务订阅 AMQP 事件 + 调 Publisher REST API 拉取定义。

## 1) APIM 4.x 发布架构(Classic/Synapse 网关)
- Publisher 创建 API → 生成 **Revision(修订版快照,最多 5 个)** → Deployments 页面勾选 Gateway Environment 部署 `/apis/{apiId}/deploy-revision`。
- **通知通道**:TM(Traffic Manager)将 API/Application/策略变更事件发布到内置 **JMS(AMQP 5672)topic**(`org.wso2.apimgt.notification.stream`),网关订阅 JMS 后,再从控制面**拉取 API artifact(Synapse XML)** 更新内存映射;这是 "JMS notification + artifact pull" 模型(不是直接 thrift 下发路由)。
- **数据通道**:限流/分析数据走 **Binary(protobuf over TCP,推荐)或 Thrift** data publisher(多 DC 文档明确需自定义 4 个 data publisher:notification/token revocation/keymgt/webhooks)。
- **Event Hub 节点**:分布式/多 DC 部署中承担 broker(JMS)+ artifact 提供角色,`deployment.toml` 配置 `[apim.event_hub]`;多 DC 间 JMS 同步**不 OOTB,需自定义 data publisher**。
- 网关环境注册:4.5 前 `gateway-environments.xml` + `deployment.toml`;4.6+ Admin Portal 动态注册(Admin REST API `/environments`)。
- 另有内部 **Gateway API v2.3**(`/api/am/gateway/v2`,11 个路径:`/api-artifact`、`/redeploy-api`、`/end-points`、`/local-entry`、`/sequence` 等)——这是 Classic 网关拉 artifact 的内部接口,非公开扩展契约。

## 2) 官方网关类型定位
| 网关 | 定位 |
|---|---|
| **Classic Gateway (Universal/Synapse)** | 内置全功能 Java 网关(旧称 Synapse/Universal),JMS 同步,功能最全 |
| **Kubernetes Gateway / APK**(APK = API Platform for Kubernetes) | 云原生,Envoy 数据面 + K8s CRD(API/HTTPRoute)。注意:架构文档里它**基于 Envoy 与 Gateway API CRD 构建,但不是直接用 envoyproxy/gateway,而是自带 Go control plane 产出 xDS**(未在本次源码级最终确认,标注"需源码复核") |
| **Platform Gateway**(4.6+/API Platform,`wso2/api-platform` 仓库) | 轻量混合部署网关,docker-compose 发行,registration token 主动连控制面,subscription-less + Policy Hub 策略 |
| **Choreo Connect / Immutable Gateway**(product-microgateway,旧) | 已让位,文档在修复断链 |
| **Federated Gateways**(4.6+) | AWS/Azure/Kong(Konnect 只读 + K8s 只读)/Envoy Gateway(K8s,只读发现),及 **Custom Gateway Agent** |

关键限制:**K8s 版 Envoy Gateway / Kong 连接器目前主要是 Read-Only(发现)**——Agent watch CRD(`HTTPRoute`/`Service`/`BackendTrafficPolicy`/`SecurityPolicy`)反向上报成 APIM API;Write/双向只对 AWS/Azure/Kong Standalone 明确。Higress 兼容 Gateway API HTTPRoute CRD,理论上可复用该 agent 的 watch 机制,但未确认(需自建/改 agent)。

## 3) REST API 能力(完整 swagger 随产品发布)
- Swagger UI/Docs:
  - Publisher v4:`https://apim.docs.wso2.com/en/latest/reference/product-apis/publisher-apis/publisher-v4/publisher-v4/`(Redoc,yaml:`.../publisher-v4/publisher-v4.yaml`,我已拉取 655KB,约 130+ 路径)
  - Admin v4:`.../admin-apis/admin-v4/admin-v4/`
  - 产品内置:`https://<host>:9443/api/am/publisher/v4/docs`、`/api/am/admin/v4/docs`
- Publisher 关键端点(base `/api/am/publisher/v4`):
  - 创建/查询:`POST /apis`、`GET /apis`、`GET /apis/{apiId}`、`POST /apis/import-openapi`(可直接拿 OpenAPI 建 API)
  - **取定义**:`GET /apis/{apiId}/swagger`(OpenAPI)、`GET /apis/{apiId}`(含 endpointConfig)、`GET /apis/{apiId}/resource-policies`
  - 发布:`POST /apis/change-lifecycle?(action=Publish)`
  - 修订/部署:`POST /apis/{apiId}/revisions`、`GET .../revisions`、`POST .../deploy-revision`、`POST .../undeploy-revision`、`GET .../deployments`
  - 导入导出:`/apis/import`、`/apis/export`
- Admin v4 关键:`/environments`、`/environments/{id}/gateways`、`/gateways`、`/workflows`(外部工作流审批回调)
- **没有现成的"导出 Spring Cloud Gateway route / Higress Ingress 注解格式"端点**——需自己从 swagger+api DTO 映射。

## 4) 事件通知机制
- **AMQP 直订(最实用)**:内置 broker 5672,订阅 notification stream 即可收到 API 发布/修订事件(官方 K8s gateway agent 的 helm 参数就叫 `controlPlane.eventListeningEndpoints="amqp://admin:pwd@host:5672"`,证明外部组件走这条路)。队列/stream 名:org.wso2.apimgt.notification.stream。事件负载为内部 DTO(API 更新通知含 provider/name/version,需再回调 REST API 拉全量)。
- **Workflow Executor**:`APIPUBLISH` 等生命周期可插自定义 workflow(HTTP 回调审批,Admin API `/workflows/update-workflow-status`),适合在 Publish 动作处挂钩,但属于审批流,不是普通 webhook。
- 另有 Key Manager 事件、token revocation stream;Developer Portal 的 "Webhooks API"(scenario10)是**业务 API 能力**,不是控制面事件推送。
- **无通用 "API 发布 → 外部 HTTP webhook" OOTB 功能**(未确认有,文档未列出;需自建)。
- Analytics event publisher 可把分析事件发外部,但不适合做配置同步。

## 5) 第三方网关适配的既有实践
- 官方仓库:**wso2-extensions/apim-gw-connectors**(原 apim-gw-agents,GitHub 已 301 重定向),内含 `aws/`、`kong/`(standalone + k8s)、`envoygateway/`、`common-agent/helm`。AWS agent 文档直接给为自定义 agent 参考实现。
- 扩展 SPI(OSGi jar 放 `repository/components/dropins/`):
  - `GatewayAgentConfiguration`:getType / getConnectionConfigurations(Admin Portal 表单)/getDefaultHostnameTemplate / **getGatewayFeatureCatalog**(有 feature catalog JSON 控制 Publisher UI 能力裁剪)
  - `GatewayDeployer`:**init / deploy / undeploy / validateApi / transformAPI / getAPIExecutionURL / getType**
  - Admin Portal 注册网关环境 → Publisher Deployments 勾选即回调你的 deploy(),拿到 API 模型后可自行推 SCG Actuator/Nacos 或 Higress K8s API。
  - 样例工程:文档附件 `custom.gw.client.zip`;Synapse feature catalog 示例在 `wso2/carbon-apimgt`(v9.31.86 tag)`.../gatewayFeatureCatalog/synapse-gateway-feature-catalog.json`。
- 社区/第三方:未发现成熟的 APISIX/Kong-OSS/Spring Cloud Gateway 公开 adapter(GitHub 搜索受限流未跑完,标注**未完全确认**;官方生态内无)。

## 6) APK 架构 & Higress 复用判断
- APK = Envoy(Go control plane + K8s CRD:API、Authentication、RateLimit 等 Gateway API 风格 CR),配置经 config deployer 服务下发(`/api/configurator/apis/generate-k8s-resources`,见 Envoy Gateway federation helm 参数)。
- **不能让 Higress 直接"复用 APK 的 xDS"**(私有 xDS 契约、与 APK 策略 CRD 耦合;未确认其 xDS 对第三方 envoy 稳定开放)。
- **可行的复用层是 Kubernetes Gateway API / HTTPRoute CRD**:官方 federated Envoy Gateway agent 就是 watch 标准 `HTTPRoute/Service/BackendTrafficPolicy/SecurityPolicy` 做发现;Higress 本身实现 Gateway API,可以:
  - (a) 让 APIM 把 Higress 当作 "Envoy Gateway" 类型联邦环境(只读发现方向),或
  - (b) 自定义 deployer 生成 Higress CR(`HTTPRoute` + Higress 的 `McpBridge/IstioIngress` 等)。

## 最可行适配方案(3 候选)

**方案 A(推荐):自定义 Gateway Agent(OSGi `GatewayDeployer`)**
- 优点:官方一等扩展点、与发布事务同步(成功/失败直接反映在 Deployments UI)、能裁剪 UI feature catalog、生命周期与 APIM 版本绑定清晰;有 AWS agent 源码和 custom.gw.client 样例;一个 bundle 内可同时适配 SCG(推 Nacos/Actuator)与 Higress(k8s client 写 CRD)。
- 缺点:Java/OSGi 开发,与 APIM 版本耦合升级;deploy() 内调外部系统需做好超时/重试;4.6+ 才成熟,4.0–4.5 需验证 SPI 是否齐备(feature 较新)。

**方案 B:外部 Sidecar 服务 = AMQP 订阅 + Publisher/Admin REST API 轮询/拉取**
- 做法:独立 Go/Java 服务订阅 5672 notification stream(仿官方 common-agent 的 `eventListeningEndpoints`),收到事件后调 `/api/am/publisher/v4/apis/{id}/swagger` + API DTO,转换成 SCG routes(Nacos 配置)与 Higress HTTPRoute CRD 下发;定期 reconciliation 兜底。
- 优点:与 APIM 进程解耦、语言无关、不动 dropins、适配 4.x 全版本(JMS 架构 3.x 起就有)、可统一双网关。
- 缺点:事件格式是内部 DTO(版本间可能变);最终一致、非事务;需自己处理 AMQP 鉴权/TLS、去重、全量对账;订阅事件 stream 属内部机制(官方 agent 在用,但非公开稳定性承诺)。

**方案 C:走标准 K8s CRD 层(只解决 Higress)+ SCG 另接**
- Higress 侧直接注册为 4.6+ "Envoy Gateway" 联邦环境或部署官方 common-agent(kong/envoy agent 改 `agent.gateway`),让 APIM 与 HTTPRoute CRD 双向;SCG 侧仍需 A 或 B。
- 优点:Higress 侧零/少开发,跟随官方升级;用 Kubernetes Gateway API 标准。
- 缺点:官方 Envoy/Kong k8s connector 目前主打**只读发现**(API 先在集群里建),APIM→Higress 的 write 路径未确认,可能仍要改 agent;SCG 无法复用;Higress 专有策略(鉴权/限流)映射不到 WSO2 安全模型(JWT plugin 需对齐)。

**建议**:SCG 必须自研(A 或 B);若想一个组件统一双网关、且接受 Java,选 **A**;若团队偏 Go/云原生且要版本解耦,选 **B**(仿 wso2-extensions/apim-gw-connectors/common-agent 模式),Higress 用 CRD、SCG 用 Nacos。鉴权注意:两条链路都要让外部网关对齐 WSO2 KM 的 JWT 校验(Kong 文档要求上传 KM PEM、挂 JWT plugin),SCG 需自建 JWT 校验 filter。

## 主要来源
- 联邦网关总览/自定义 Agent(4.6+):GitHub wso2/docs-apim `en/docs/api-gateway/federated-gateways/overview.md`、`configure-custom-gateway-agent.md`(线上 URL:https://apim.docs.wso2.com/en/latest/api-gateway/federated-gateways/overview/ ,官网有 Cloudflare 挑战,我从官方文档仓库 master/4.5.0 分支直接取源)
- Envoy Gateway/Kong federation(4.6+):同目录 `envoygateway/...discover-apis-on-eg-gateway-in-kubernetes.md`、`kong/...`
- 连接器源码:https://github.com/wso2-extensions/apim-gw-connectors (含 common-agent helm、eventListeningEndpoints AMQP 参数)
- 架构(JMS notification stream、TM、Classic/K8s/Immutable gateway):docs `get-started/apim-architecture.md`;多 DC data publisher(thrift/binary、4 个 stream):`install-and-setup/.../multi-dc-deployment-pattern-1.md`
- Platform Gateway:`api-gateway/platform-gateway/*`;发布/revision:`deploy-api-to-gateway.md`
- REST swagger:docs 仓库 `reference/product-apis/{publisher-apis/publisher-v4,admin-apis/admin-v4,gateway-apis/gateway-v2,devops-apis/devops-v0}/*.yaml`;线上 https://apim.docs.wso2.com/en/latest/reference/product-apis/overview/
- APK:https://github.com/wso2/apk、https://apk.docs.wso2.com(1.3 quickstart 链接);Choreo Connect:https://github.com/wso2/product-microgateway
- SPI 样例引用:carbon-apimgt `gatewayFeatureCatalog/synapse-gateway-feature-catalog.json`;文档附件 custom.gw.client.zip

## 未确认/需自建(明确标注)
1. APK xDS 控制面能否被 Higress/第三方 Envoy 直接消费——未做源码级确认,判断不可行,需复核 wso2/apk。
2. 4.0–4.5 是否已含 GatewayDeployer SPI(联邦网关为 4.6+ 特性,旧版大概率需走方案 B)。
3. 官方 Envoy Gateway connector 的 write-only/双向写能力(文档仅演示 read-only 发现)。
4. notification stream 负载的版本兼容承诺、无 OOTB 控制面 webhook(基于文档缺失判断,需自建)。
5. 无现成 SCG/APISIX adapter(GitHub API 当时限流,搜索未穷尽)。

## 产出文件
- `/tmp/wso2docs/1–15.md`:抓取的 15 篇官方文档源文(联邦网关、架构、revision、Platform Gateway 等)
- `/tmp/pub.yaml`(Publisher v4 OpenAPI)、`/tmp/admin-v4.yaml`、`/tmp/gwapi.yaml`(Gateway v2.3 内部 API)、`/tmp/devops.yaml`
- `/tmp/docs-apim-450/`:4.5.0 版文档仓库浅克隆(用于确认旧版架构)

**遇到的问题**:apim.docs.wso2.com 被 Cloudflare Turnstile 拦截(curl 403、浏览器验证未过),archive.org 与 r.jina.ai 在本机网络不可达,GitHub API 后期匿名限流;均通过官方文档 GitHub 源仓库(wso2/docs-apim 分支 master/4.5.0)raw 文件绕过,内容为一手官方资料。