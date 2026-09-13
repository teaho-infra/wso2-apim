# 踩坑清单（scg-wso2-management）

## 1. Maven 构建在下载阶段卡死（无报错、CPU≈0）

**现象**：`mvn clean install` 拉依赖时日志停在某个 `maven.aliyun.com` 构件上，
8+ 分钟无输出，`jstack` 显示主线程 `WagonTransporter` 卡在
`SSLSocketImpl.readApplicationRecord` → `receiveResponseHeader`（连接挂起、无读超时）。

**根因**：同时配置了两套代理且冲突——
- `settings.xml` 的 `<proxies>` 带了 `nonProxyHosts=*.aliyun.com`（阿里云直连）；
- 又在 `MAVEN_OPTS` 里设了 `-Dhttp.proxyHost=127.0.0.1 -Dhttps.proxyHost=7890`，
  JVM 系统属性这套**没有** nonProxyHosts，把 aliyun 也强制走 mihomo，连接 stall。

**解决**：去掉 `MAVEN_OPTS` 里的 `-D*.proxyHost`，代理只由 `settings.xml` 管理；
并给 wagon 加读超时/关死连接复用：

```bash
mvn clean install -Dmaven.test.skip=true -Dmaven.javadoc.skip=true -B \
  -Dmaven.wagon.http.retryHandler.count=3 \
  -Dmaven.wagon.httpconnectionManager.ttlSeconds=60 \
  -Dmaven.wagon.rto=60000 -Dmaven.wagon.http.readTimeout=60000 \
  -Dhttp.keepAlive=false -Dmaven.wagon.http.pool=false \
  -s infra/wso2-apim/maven-settings.xml
```

## 2. settings.xml 的 mirrorOf 不能写 `*`

阿里云镜像**没有** WSO2 私有构件（carbon/apimgt/osgi），`mirrorOf=*` 会把
`maven.wso2.org` 请求也转到阿里云导致构件缺失。必须 `mirrorOf=central`，
并在 profile 里显式加 wso2 releases/snapshots/thirdparty 仓库。

## 3. SCG starter 改名 + 版本下限（实测纠正）

- 旧坐标 `spring-cloud-starter-gateway` 只到 SCG 4.1.x。
- 新坐标 `spring-cloud-starter-gateway-server-webflux` **从 SCG 4.3.0（Spring Cloud 2025.0.x）才进入 BOM**；
  2024.0.x（SCG 4.2.x）的 BOM 里没有它，直接依赖会报
  `version was missing / BOM 未管理`。本项目用 Boot 3.5.16 + SC 2025.0.3（SCG 4.3）。
- actuator gateway 写端点需 `management.endpoint.gateway.access=unrestricted`。

## 4. Actuator 热写路由的两个坑

- 同一 route id 重复 POST 会导致 `GET /routes` 500；更新必须**先 DELETE 再 POST**。
- POST/DELETE 后必须 `POST /actuator/gateway/refresh` 才生效。

## 5. Higress standalone 下发通道

- 不裸写 Nacos dataId（内部编码格式未公开）。走标准 Ingress（`ingressClassName: higress`）。
- standalone all-in-one 可直接 `docker cp` yaml 到容器
  `/data/{ingresses,services,endpoints}/`，内部 api-server watch 生效。
- 独立 Higress 容器访问宿主 downstream：Endpoints 地址用 `docker0`（172.17.0.1）。
- **docker cp 是 merge 语义**，不会删除目标目录里源目录没有的文件。adapter 在
  拷贝前必须清空本地 tmp 的 `wso2-*.yaml`，且对容器端 stale 文件单独
  `docker exec rm`，否则历史路由会被「复活」。

## 6. Publisher v4 REST 建 API 的三个坑

- **`endpointConfig` 必须是 JSON 对象，不能是字符串**。传 `json.dumps(...)` 字符串
  会得到 500，服务端 `PublisherCommonUtils.validateEndpoints` 抛
  `ClassCastException: String cannot be cast to Map`。
  正确：`"endpointConfig": {"endpoint_type":"http","production_endpoints":{"url":"http://host:port"}}`。
- **列表搜索语法是 `query=status:PUBLISHED`**，不是 `lifecycleStatus:PUBLISHED`
  （后者恒返回 0 条）。且生命周期刚变更后搜索索引有秒级延迟，adapter 再用 DTO 的
  `lifeCycleStatus` 字段客户端复核一次。
- **下线动作名带空格**：`action=Demote to Created`（URL 编码）；驼峰
  `DemoteToCreated` 报 903234「Unsupported state change action」。已 PUBLISHED 再
  Publish 会 400（正常业务校验），只有 CREATED→Publish 合法。

## 7. 源码构建：integration 测试模块的空 jar 不影响产品产物

长构建中网络 stall 会在本地仓留下 **0 字节 jar**（如 `zookeeper-3.4.14.jar`），
导致 `all-in-one/integration/tests-common/admin-clients` 编译报
`ZipException: zip END header not found`。但该模块属集成测试辅助，**产品分发
`wso2am-4.7.0.zip` 在更早的 distribution 模块已生成**。`unzip -t` 校验通过即可
直接解压启动，无需等 itests；如要干净构建，删除该空 jar 后 `-rf` 续构即可。
另：部分 `*.wso2v1` 第三方包（如 juddi）只存在于 `groups/wso2-public`，
`thirdparty` 仓里 404，settings 必须显式加 wso2-public group。

## 8. 源码产物运行：offset 避让 + 启动确认

- `repository/conf/deployment.toml` 的 `[server]` 下加 `offset = 100`，
  所有端口 +100（管理 https 9443→9543）。4.7 启动脚本是 `bin/api-manager.sh`，
  无 wso2server.sh、无 `--optimize` profile 参数。
- 启动成功标志：wso2carbon.log 出现 `WSO2 Carbon started in N sec`；
  `https://127.0.0.1:9543/carbon/` 返回 302、Publisher API 返回 401 即正常。
