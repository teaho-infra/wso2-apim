# Spring Cloud Gateway 与 Higress 动态路由管理机制调研报告

调研基于官方文档与源码实证(Spring Cloud Gateway 4.2.x/5.0.3 文档、alibaba/higress main 与 v1.4.2 源码、higress-console 源码、1.4.2 standalone docker-compose 实包)。**未确认项已明确标注**。

---

## A. Spring Cloud Gateway(SCG)

### A1. Actuator 端点(最直接的外部推送手段)

- **依赖与开启**:`spring-cloud-starter-gateway`(SCG 4.x,基于 WebFlux;3.x artifact 同名)+ `spring-boot-starter-actuator`,并显式暴露:
  ```properties
  management.endpoints.web.exposure.include=gateway
  management.endpoint.gateway.access=unrestricted   # 关键:read-only 时禁止增删/refresh
  ```
  SCG 4.x 起 `/gateway` 端点**默认禁用**,需设置 `management.endpoint.gateway.access=read-only|unrestricted`;需要写能力必须 `unrestricted`(或旧式 `enabled=true`)。
- **端点清单**(基础路径 `/actuator/gateway`):
  | 方法/路径 | 用途 |
  |---|---|
  | `GET /globalfilters`、`/routefilters`、`/routepredicates`、`/routedefinitions` | 只读元信息 |
  | `GET /routes`、`GET /routes/{id}` | 查询路由(5.x 默认 verbose 格式,predicate 是人类可读字符串) |
  | `POST /routes/{id}` | 创建单条路由,Body 为 RouteDefinition JSON,返回 **201** |
  | `POST /routes` | 批量创建(List<RouteDefinition>,任一失败整体回滚) |
  | `DELETE /routes/{id}` | 删除一条,返回 200 |
  | `POST /refresh` | 发布 `RefreshRoutesEvent` 清缓存使变更生效;5.x 支持 `?metadata=group:xxx` 局部刷新 |
- **POST Body 格式(predicate/filter 必须用 shortcut DSL 字符串,与 GET 返回格式不同)**:
  ```json
  {
    "predicates": ["Path=/mypath/**", "Method=GET"],
    "filters": ["StripPrefix=1"],
    "uri": "http://backend-service:8080",
    "order": 0,
    "metadata": {"group": "api-publish"}
  }
  ```
- **重要约束**:
  - POST/DELETE 后**必须再调 `POST /refresh`** 才生效(内存操作,**亚秒级**);
  - 只能改 actuator 创建的路由;配置文件/`@Bean` 定义的路由删除返回 **404**;
  - 更新须先 DELETE 再 POST(直接重复 POST 同 id 会重复定义,后续 GET 500);
  - 默认存储是 `InMemoryRouteDefinitionRepository`(**重启丢失**);4.2.x 源码中还有 `RedisRouteDefinitionRepository`(可用 Redis 持久化);
  - 鉴权:Actuator 本身**无内建鉴权**,官方要求自行加 Spring Security/网络隔离。
- **3.x vs 4.x/5.x 差异**:4.2.x 源码出现 `GatewayControllerEndpoint`(新)与 `GatewayLegacyControllerEndpoint`(旧)双控制器;5.x 文档新增 `management.endpoint.gateway.access` 开关、verbose 格式与 metadata 局部刷新。3.x(Boot 2.x,javax)写操作同样默认开放暴露即可,无 access 开关;配置属性前缀 4.1+ 迁移为 `spring.cloud.gateway.server.webflux.*`。

### A2. Nacos 动态路由(spring-cloud-alibaba)

- **关键事实(重要纠偏)**:`spring-cloud-starter-alibaba-nacos-*` **没有官方的 RouteDefinitionRepository 实现**(2023.x 树中无任何 gateway 路由仓库类,只有 nacos-discovery 与示例)。社区通行做法是**自行实现** `RouteDefinitionRepository`(或 `RouteDefinitionLocator`)+ 监听 Nacos 配置变更发布 `RefreshRoutesEvent`;也可借助 Nacos 作为 Spring Cloud Config 源(`spring.config.import`)或第三方封装。
- **版本兼容**(Boot 3.x / SCG 4.x):
  - Spring Cloud 2023.x(含 SCG 4.1.x)→ `spring-cloud-alibaba 2023.0.x`(Jakarta,如 2023.0.1.2);
  - Spring Cloud 2024.x(SCG 4.2.x)/2025.x(SCG 5.x)→ alibaba 对应 `2024.0.x`(发布较晚,需按官方版本说明核实,**此项建议落地前查版本矩阵确认**);
  - 纯服务发现场景用 `spring-cloud-starter-alibaba-nacos-discovery` + `lb://service-name` URI,实例变更自动感知,但**路由规则本身仍需上述动态机制**。
- dataId/格式:由自定义实现决定,典型为 `xxx-routes.json`(Group `DEFAULT_GROUP`),内容为 RouteDefinition 数组;刷新延迟 = Nacos 长轮询延迟(默认约 1–10s 级,长轮询近实时)+ refresh 耗时。

### A3. 编程式 API

```java
public interface RouteDefinitionWriter {
    Mono<Void> save(Mono<RouteDefinition> route);
    Mono<Void> delete(Mono<String> routeId);
}
```
注入内置 `RouteDefinitionWriter`(Actuator 控制器内部即调用它,见 `AbstractGatewayControllerEndpoint`),save/delete 后用 `ApplicationEventPublisher` 发布 `RefreshRoutesEvent`(删除事件 `RouteDeletedEvent`)。适合在进程内做适配层;外部控制面仍应走 Actuator HTTP 或 Nacos。

来源:
- https://docs.spring.io/spring-cloud-gateway/reference/spring-cloud-gateway-server-webflux/actuator-api.html
- https://github.com/spring-cloud/spring-cloud-gateway/blob/4.2.x/spring-cloud-gateway-server/src/main/java/org/springframework/cloud/gateway/actuate/AbstractGatewayControllerEndpoint.java
- https://github.com/spring-cloud/spring-cloud-gateway/tree/4.2.x/spring-cloud-gateway-server/src/main/java/org/springframework/cloud/gateway/route
- https://github.com/alibaba/spring-cloud-alibaba/tree/2023.x

---

## B. Higress

### B1. 路由 CRD 到底是什么(已从 console SDK 源码证实)

- **路由的权威资源就是标准 Kubernetes Ingress**(`networking.k8s.io/v1` 的 `V1Ingress`),Console 的 `RouteServiceImpl` 直接 `createIngress/replaceIngress/deleteIngress/listIngress`,Route ↔ Ingress 做模型互转。**没有独立的"路由 CRD"**;能力靠 **Ingress annotations** 扩展(`higress.io/*`,如重写、限流、重试、灰度、McpBridge destination 等)。
- 周边扩展资源才是 CRD/Istio CR:`McpBridge`(服务来源)、`WasmPlugin`、`EnvoyConfig*`、`TlsSecret`、`consumer`、`http2-rpc` 等;新版还支持 K8s **Gateway API**(源码中有 `gateway_api.go`)。
- **1.x→2.x 差异(部分已证实,部分标注)**:1.x(如 v1.4.2)K8s 模式 = HigressController watch 带 `ingressClassName: higress` 的标准 Ingress;standalone 模式内置一个轻量 **api-server**(`higress/api-server` 镜像)对外提供 K8s API 形态,存储后端可为 **nacos 或 file**,Console 用 kubeconfig 连它。2.x 树中仍保留 `pkg/ingress/kube`(242 个文件,controller 继续 watch Ingress),并增强 Gateway API、AI 路由(`AiRoute`)、MCP 等。`MseIngressConfig` 是**阿里云 MSE 托管版**概念,开源版不使用。

### B2. Console 后端 API(注意:后端是 Java/Spring Boot,不是 Go)

- `higress-console` 容器 = Java 后端(`higress-console` 仓库 `backend/console`,Spring `@RestController`)+ 前端,默认容器端口 **8080**(standalone `CONSOLE_PORT` 默认 8080)。
- 路由接口基路径 **`/v1/routes`**(`RoutesController`):
  - `GET /v1/routes`(分页、支持按域名过滤)、`GET /v1/routes/{name}`
  - `POST /v1/routes`(新增,Body 为 Console 的 Route DTO)、`PUT /v1/routes/{name}`、`DELETE /v1/routes/{name}`
  - 其它:`/v1/domains`、`/v1/services`、`/v1/service-sources`、`/v1/consumers`、`/v1/tls-certificates`、`/v1/plugins`、AI 路由 `/v1/ai/routes` 等。
- Route DTO 字段(简化):name、domains/path predicates(支持 PRE/REGULAR/EQUAL 等匹配类型,见 `RoutePredicateTypeEnum`)、methods、upstreams(`UpstreamService`:name+port+weight)、authConfig、redirect/rewrite/rateLimit/cors 等高级策略。Console 负责把它翻译成标准 Ingress + annotations。
- 链路:Console →(client-go,kubeconfig/挂载的 sa token)→ K8s API Server(或 standalone api-server)→ HigressController → Pilot → xDS → Envoy。
- 鉴权:Console 有内建登录/会话(Session/User/ChangePassword 控制器),初始化管理员账号;API 走 Cookie Session。无鉴权直连的是底层 K8s API。
- Swagger:Console 内置 `SwaggerConfig`,可从运行实例 `/v3/api-docs`(或 swagger-ui)拿完整接口定义。

### B3. 通过 Nacos 下发配置的可行性(已用 1.4.2 standalone 实包证实)

- **1.x standalone 默认内置 Nacos 容器**:`nacos-server:v2.2.3`(`--use-builtin-nacos`),端口 **8848(HTTP)/9848(gRPC)**,命名空间默认 `higress`(可 `--nacos-ns` 改),也支持外挂 nacos(`--config-url=nacos://host:8848`)。
- 1.4.2 容器拓扑(实证 docker-compose):**nacos → apiserver(storage=nacos,8443 mTLS)→ controller(higress:8888/ready)→ pilot(15014 监控、8080 ready)→ gateway(Envoy,80/443/15020)+ console:8080**。
- 关键结论:**外部不应直接裸写 Nacos dataId**。Standalone 下控制面入口是内嵌 api-server(把 Ingress 等对象序列化存进 Nacos,dataId 为其内部编码格式,随版本可能变化),HigressController 仍按 K8s 资源语义 watch。手工往 Nacos 写配置无公开稳定的 dataId 规范,**属未公开行为,不建议对接**(社区里"直接写 Nacos dataId"的做法是 2022 年极早期架构的历史信息)。可行的"借 Nacos 下发"路径:
  1. 推荐:调 Console REST `/v1/routes` 或直接用 kubeconfig 调内嵌 api-server 写 Ingress;
  2 仅当复用客户已有 Nacos 时:让 HigressController 连该 Nacos 作存储(`--config-url`),再经 api-server 写。
- 2.x:storage 抽象保留 `--storage nacos|file`,但 dataId 格式同样未公开。**dataId 具体格式标注为未确认/不建议依赖。**

### B4. 与 Envoy/Istio 的关系及端口

- Higress = fork 自 **Istio 1.27(2.x;1.4.x 对应 Istio 1.19)+ Envoy 1.36** 的控制面 + Envoy 数据面(见主仓 `.gitmodules`:`higress-group/istio`、`envoy-1.36`)。HigressController 把 Ingress/Gateway API/McpBridge 翻译成 Istio 配置,**Pilot(discovery)通过 xDS 下发给 Envoy gateway**;扩展链路由 WasmPlugin(ECDS)下发。
- 端口:xDS gRPC **15012**(Ingress Gateway 连 Pilot 的 discovery 端口,istiod 标准端口;compose 内部网络),Pilot 监控/debug **15014**,健康 8080;Envvoy 健康 **15021**、metrics **15020**;业务 80/443。standalone compose 未把 15012 映射到宿主(内部网络通信)。

### B5. 上游服务来源

- **McpBridge CRD**(`extensions.higress.io/v1` kind `McpBridge` / "服务来源"):Console 的 `/v1/service-sources` 管理;支持注册中心类型 **Nacos(含 Naming v1/v2 watcher)、ZooKeeper、Consul、Eureka、Nacos/DNS/静态(static/static-domain)、K8s Service** 等;主仓源码实证有 `registry/nacos/v2/watcher.go`、`registry/nacos/address/address_discovery.go`(2.x)。
- Ingress backend 可以是 K8s Service(`namespace/name:port`)、注册中心服务(配合 McpBridge + `higress.io/destination` 之类注解引用注册源里的服务名)或静态域名/IP;注册中心实例变更由 MCP server watch 后经 xDS 推送,无需重启。
- 来源:
  - https://github.com/alibaba/higress(main 树、`.gitmodules`、`registry/nacos/*`)
  - https://github.com/higress-group/higress-console(RoutesController / RouteServiceImpl)
  - https://higress.io/standalone/higress-v1.4.2.tar.gz(compose/docker-compose.yml、tools/get-higress.sh)
  - https://github.com/alibaba/higress/blob/main/hgctl/pkg/installer/standalone_agent.go
  - 文档入口:https://higress.io/docs/latest/ 与仓库 https://github.com/higress-group/higress.github.io

---

## C. "无重启动态增删一条路由"最小可行手段对比

| 维度 | Spring Cloud Gateway | Higress |
|---|---|---|
| 推荐接口 | `POST /actuator/gateway/routes/{id}` + `POST /actuator/gateway/refresh`;删 `DELETE /routes/{id}` + refresh;更新=先删后建 | K8s 模式:`kubectl apply` 标准 Ingress(networking.k8s.io/v1,ingressClassName=higress);Standalone:Console `POST/PUT/DELETE http://console:8080/v1/routes[/{name}]` |
| 配置格式 | RouteDefinition JSON,`predicates:["Path=/x/**","Method=GET"]`、`filters:[...]`、`uri`(http://、lb://service) | Ingress YAML(rules.host/http.paths/backend service+port,能力靠 `higress.io/*` 注解);或 Console Route JSON(predicates/methods/upstreams/auth/redirect…) |
| 方法级路由 | `Method=GET` predicate 原生 | Ingress 原生不区分 method → 注解/路由配置(Console Route DTO 支持 methods);或 Gateway API HTTPRoute |
| 鉴权要求 | key-auth 用 `AddRequestHeader`/自定 filter 或集成 Spring Security;网关自身靠 filter | `AuthConfig`/consumer + key-auth Wasm 插件;Ingress 注解开启 |
| 上游来源 | 直连 URL 或 `lb://`(Nacos Discovery 等注册中心) | K8s Service / 静态域名 IP / McpBridge(Nacos/ZK/Consul/Eureka) |
| 生效延迟 | 内存 + refresh,**毫秒~亚秒** | controller watch + Pilot 计算 + xDS 推送,典型 **1–数秒**(无重启) |
| 持久性 | 默认 InMemory **重启丢失**;可自行接 Nacos/Redis RouteDefinitionRepository | 存 etcd / standalone 内置 Nacos(file/nacos storage),持久 |
| 鉴权(接口侧) | 无内建,须自加 Spring Security/网络隔离 | Console:管理员账号+Cookie Session;K8s API:kubeconfig/RBAC;mTLS(api-server 8443) |
| Nacos 直推可行性 | 无官方实现,需自定义 `RouteDefinitionRepository` 监听 dataId;长轮询近实时 | 不建议裸写 Nacos dataId(内部格式不公开);经 api-server/Console 间接使用;McpBridge 用 Nacos 做服务发现是官方路径 |

## 适配层落地建议
- 统一中间模型 `{path, upstream, method, auth}` → SCG:生成 RouteDefinition(predicates=Path+Method,uri=`lb://` 或 http,filters 放鉴权 header),POST 后 refresh;→ Higress:生成标准 Ingress(method/auth 用 higress 注解)调 Console `/v1/routes` 或 K8s API,upstream 预先在 McpBridge/服务来源注册。
- **未确认/风险标注**:① spring-cloud-alibaba 2024.x/2025.x 与 SCG 4.2/5 的精确兼容版本需查官方版本矩阵;② Higress standalone 存 Nacos 的 dataId 编码格式未公开,禁止直接依赖;③ Higress 2.x 文档站点部分页面抓取 404,2.x standalone 与 1.x compose 的细节差异建议以目标版本 tar 包为准(本次实证为 v1.4.2)。

**本次产出**:下载并解包实证了 `/tmp/higress-standalone-1.4.2/`(compose 拓扑与环境变量),抓取了 SCG 4.2 控制器源码与 5.0.3 官方 Actuator 文档、higress/higress-console 源码树。未创建项目文件;报告即唯一交付物。