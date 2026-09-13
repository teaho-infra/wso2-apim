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

## 3. SCG 4.2 starter 改名

Spring Cloud 2024.0.x（SCG 4.2.x）起 starter 为
`spring-cloud-starter-gateway-server-webflux`；旧坐标
`spring-cloud-starter-gateway` 只到 4.1.x。且 actuator gateway 写端点需
`management.endpoint.gateway.access=unrestricted`。

## 4. Actuator 热写路由的两个坑

- 同一 route id 重复 POST 会导致 `GET /routes` 500；更新必须**先 DELETE 再 POST**。
- POST/DELETE 后必须 `POST /actuator/gateway/refresh` 才生效。

## 5. Higress standalone 下发通道

- 不裸写 Nacos dataId（内部编码格式未公开）。走标准 Ingress（`ingressClassName: higress`）。
- standalone all-in-one 可直接 `docker cp` yaml 到容器
  `/data/{ingresses,services,endpoints}/`，内部 api-server watch 生效。
- 独立 Higress 容器访问宿主 downstream：Endpoints 地址用 `docker0`（172.17.0.1）。
