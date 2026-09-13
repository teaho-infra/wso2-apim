# WSO2 API Manager 4.x 从源码构建到本地运行调研报告（2026-09）

> 调研时间：2026-09-13。所有版本号/命令均来自官方 GitHub、官方文档源码（wso2/docs-apim）和 Docker Hub 实测页面，未实测的项明确标注。

## 0. 结论速览（针对本机 Ubuntu 24.04 + 46G RAM）

- **最新稳定版：WSO2 API Manager 4.7.0**（GitHub release，2026-04-29）；上一版 4.6.0（2025-11-04）。
- **实验用途最快路径不是源码构建，而是直接下 release zip 或 docker pull**：
  - zip：`https://github.com/wso2/product-apim/releases/download/v4.7.0/wso2am-4.7.0.zip`（已实测 HTTP 200，可直连 GitHub release CDN）
  - 镜像：`docker pull wso2/wso2am:4.7.0`（= `latest`，amd64/arm64，压缩后约 714 MB；另有 `4.7.0-alpine` 约 650 MB、`4.7.0-rocky`）
- 运行 JDK：**JDK 21**（4.7.0 官方测试 JDK 为 Temurin 21、25；4.4.0/4.5.0/4.6.0 测试 11/17/21）。本机用 JDK 21 即可。
- 默认账号：**admin / admin**；控制台 https://localhost:9443/carbon ，Publisher `/publisher`，DevPortal `/devportal`。
- 4.x 已**不再支持 all-in-one 内的 `-Dprofile=...` 单进程裁剪**；4.7 的最小化方式是跑独立组件分发包（api-control-plane / traffic-manager / universal-gateway 各自的 zip 和 docker 镜像）。

---

## 1. 源码仓库、版本、JDK/Maven/Node 要求

### 1.1 仓库
- 主仓库（产品分发包聚合工程）：https://github.com/wso2/product-apim
  - 4.7.0 顶层模块：`all-in-one-apim/`、`api-control-plane/`、`gateway/`、`traffic-manager/`
- 后端核心组件：https://github.com/wso2/carbon-apimgt （4.7.0 对应版本 **9.33.122**）
- 门户前端（React）：https://github.com/wso2/apim-apps （4.7.0 对应 UI 版本 **9.3.194**）
- 文档源码（md）：https://github.com/wso2/docs-apim （分支 4.4.0/4.5.0/4.6.0/4.7.0）
- 问题跟踪：https://github.com/api-manager/issues
- 来源：
  - https://github.com/wso2/product-apim/blob/v4.7.0/CONTRIBUTING.md
  - https://github.com/wso2/product-apim/blob/v4.7.0/all-in-one-apim/pom.xml

### 1.2 版本
| 版本 | 状态 | 发布时间 | 测试 JDK（Temurin） |
|---|---|---|---|
| 4.7.0 | 最新稳定 release | 2026-04-29 | **21, 25** |
| 4.6.0 | 稳定 | 2025-11-04 | 11, 17, 21 |
| 4.5.0 | 稳定 | 未确认（GitHub API 限流未取到精确日期） | 11, 17, 21 |
| 4.4.0 | 稳定 | 未确认 | 11, 17, 21 |

来源：
- https://github.com/wso2/product-apim/releases （tags/releases API 实测：v4.7.0 GA 于 2026-04-29，v4.6.0 于 2025-11-04）
- https://github.com/wso2/docs-apim/blob/master/en/docs/reference/product-compatibility.md （4.7.0：Temurin 21, 25；DBMS：MySQL 8.4 / Oracle 19c,23c / MSSQL 2022 / PostgreSQL 18；OS：Ubuntu 24.04、Windows Server 2022）
- 4.4/4.5/4.6：分支 `4.4.0`/`4.5.0`/`4.6.0` 的 `en/docs/install-and-setup/setup/reference/product-compatibility.md`（均为 Temurin 11,17,21）

### 1.3 JDK / Maven / Node
- **运行**：JDK 21（README 原文："This product requires a JDK to run. We support JDK v21."）。
  来源：https://github.com/wso2/product-apim/blob/v4.7.0/README.md
- **从源码构建的 JDK**：4.7.0 的 CONTRIBUTING.md 仍写 "Install Java SE Development Kit **11**" + "Apache Maven 3.x.x"。这与运行要求（21）存在明显不一致，**官方构建文档疑似滞后，未确认 11 是否真能构建 4.7.0**（4.7 docker 镜像内实际装的是 Temurin JDK 25）。
  建议：**用 JDK 21 构建 4.7.0**（运行兼容矩阵内、且与内核 carbon-kernel 4.11.x 匹配）；若 enforcer 报错再切换。
  来源：https://github.com/wso2/product-apim/blob/v4.7.0/CONTRIBUTING.md ；https://github.com/wso2/docker-apim/blob/v4.7.0.2/dockerfiles/ubuntu/apim/Dockerfile
- **Maven**：官方只写 "Apache Maven 3.x.x"，未指定下限小版本（**精确最低版本未确认**），建议 Maven 3.8/3.9。无 mvnw（源码树无 Maven Wrapper，未发现）。
- **Node/npm：构建 product-apim 本身不需要 Node**。Publisher/DevPortal/Admin 三个 React 门户以预先发布好的 Maven 构件（`carbon.apimgt.ui.version=9.3.194`）形式从 WSO2 Nexus 拉取并打进 zip。只有当你要改前端、单独构建 `wso2/apim-apps` 时才需要：
  - **Node.js 22.x 或更新的 LTS**（apim-apps 官方 README 要求；本机 Node 24 满足）
  - 可选 Maven + JDK 1.8（仅当要把门户构件并进整个产品分发时）
  来源：https://github.com/wso2/apim-apps/blob/v9.3.194/README.md

### 1.4 Maven 仓库（构建时必须可达）
根 pom 显式声明：
- `https://maven.wso2.org/nexus/content/groups/wso2-public/`（id=wso2-nexus，依赖 + 插件）
- `https://dist.wso2.org/maven2`（插件仓）
- 其余走 Maven Central。
来源：https://github.com/wso2/product-apim/blob/v4.7.0/pom.xml

---

## 2. 从源码构建

### 2.1 官方步骤（来源：v4.7.0 CONTRIBUTING.md）
```bash
git clone https://github.com/wso2/product-apim.git
cd product-apim
git checkout v4.7.0
# 二选一：
mvn clean install                            # 含测试
mvn clean install -Dmaven.test.skip=true     # 跳过单元/集成测试（官方原话）
```

### 2.2 产物位置（4.7.0 与旧版路径不同，注意！）
- 官方文档原文：binary distribution 在
  `product-apim/all-in-one-apim/modules/distribution/product/target/`
- 产物文件名：**`wso2am-4.7.0.zip`**（assembly 中 `${project.version}` 实测；distribution 模块 artifactId=wso2am）
- 组件分发构建则在各自模块下，产物对应：
  - `wso2am-acp-4.7.0.zip`（API Control Plane）
  - `wso2am-tm-4.7.0.zip`（Traffic Manager）
  - `wso2am-universal-gw-4.7.0.zip`（Classic/Universal Gateway）
  （命名依据 docker-apim 各 Dockerfile 的 `WSO2_SERVER_NAME` + release 下载 URL）
- 同时产出 source 分发包。
来源：
- https://github.com/wso2/product-apim/blob/v4.7.0/CONTRIBUTING.md
- https://github.com/wso2/product-apim/blob/v4.7.0/all-in-one-apim/modules/distribution/product/pom.xml
- https://github.com/wso2/docker-apim/tree/v4.7.0.2/dockerfiles/ubuntu

### 2.3 时长 / 磁盘 / 内存
- 官方**没有**公布构建时长/内存数字（**未确认**）。
- 工程规模参考：`all-in-one-apim/pom.xml` 聚合 carbon-apimgt 9.33.x、carbon-kernel 4.11.18、carbon-identity 5.27.x、analytics、mediation 等大量 WSO2 构件，首次构建需从 wso2-nexus 拉取大量依赖（数量级：上千 jar/p2 构件）。
- 经验性预期（非官方，仅供参考）：首次构建 30–90 分钟，强依赖网络；本地 Maven 仓库会占数 GB；建议给 Maven 至少 `-Xmx2g~4g`（`export MAVEN_OPTS="-Xmx4g"`），整机 46G RAM 无压力，369G 磁盘充足。
- 注意 p2/carbon 插件对 JDK 较敏感，若 JDK 21 构建失败，可按 CONTRIBUTING 用 JDK 11 重试（但 4.7 运行仍用 21）。

---

## 3. 本地运行（all-in-one）

### 3.1 启动（zip 解压后）
```bash
unzip wso2am-4.7.0.zip
cd wso2am-4.7.0/bin
sh api-manager.sh            # 前台（官方文档命令）
sh api-manager.sh start      # 后台守护
sh api-manager.sh stop|restart|version
sh api-manager.sh --debug 5005   # 调试端口 5005
```
Windows：`api-manager.bat --run`。
成功标志：日志出现 `WSO2 Carbon started in 'n' seconds`。
注：4.x 起脚本名就是 **`api-manager.sh`**（旧 3.x 时代的 `wso2server.sh` 已不存在）。
来源：
- https://github.com/wso2/docs-apim/blob/master/en/docs/install-and-setup/install/installing-the-product/running-the-api-m.md
- https://github.com/wso2/product-apim/blob/v4.7.0/INSTALL.txt
- https://github.com/wso2/product-apim/blob/v4.7.0/all-in-one-apim/modules/distribution/product/src/main/startup-scripts/api-manager.sh

### 3.2 默认访问地址（offset=0）
| URL | 用途 |
|---|---|
| https://localhost:9443/carbon | Carbon 管理控制台 |
| https://localhost:9443/publisher | API Publisher |
| https://localhost:9443/devportal | Developer Portal |
| https://localhost:9443/admin | Admin Portal |
| http://localhost:9763/... | 对应 HTTP（一般重定向到 https） |

默认凭据：**admin / admin**（README 明确给出）。

### 3.3 默认端口表（官方文档，API-M runtime，offset 0）
| 端口 | 协议/用途 |
|---|---|
| 9443 | HTTPS servlet（carbon/publisher/devportal/admin） |
| 9763 | HTTP servlet |
| 8243 | Passthrough/NIO **HTTPS**（网关调用入口） |
| 8280 | Passthrough/NIO **HTTP**（网关调用入口） |
| 5672 | 内置 Message Broker（AMQP，限流/事件） |
| 9711 | 限流事件 SSL（Thrift/binary 数据发布，Traffic Manager） |
| 9611 | 限流事件 TCP |
| 10389 | 嵌入式 LDAP |
| 9099 | WebSocket 端口 |
| 8000 | Kerberos KDC |
| 11119?/9999 | 11111、9999（集群/管理相关，文档表内列出） |
| 4000 / 45564 | WKA / multicast 集群成员发现（仅相应 membership scheme 时开放） |
（另：JVM 调试 5005 为手工开启；端口可用 `[server] offset` 整体偏移。）
来源：https://github.com/wso2/docs-apim/blob/master/en/docs/reference/default-product-ports.md

### 3.4 硬件/DB
- 官方系统要求：最小 2 核、**4 GB RAM**（JVM 2 GB + OS 2 GB）、10 GB 磁盘；生产建议 RHEL/Ubuntu LTS。
- 默认内置 **H2** 嵌入式库，开发/测试可直接零配置启动（生产官方建议 MySQL/Oracle/PostgreSQL/MSSQL）。
来源：https://github.com/wso2/docs-apim/blob/master/en/docs/install-and-setup/install/installation-prerequisites.md
（单机实验实际常驻堆通常 1–2 GB 级别，官方硬性下限写的是 512 MB heap 即可跑典型流量——同页。）

---

## 4. Docker / docker-compose

### 4.1 官方镜像（Docker Hub 实测页面 2026-09）
- 仓库：**`wso2/wso2am`**（publisher: wso2apim）
- 标签：`4.7.0`（= `latest`，约 714 MB compressed，linux/amd64 + arm64）、`4.7.0-alpine`（约 650 MB）、`4.7.0-rocky`（约 845 MB）；`4.6.0` 系列同理。
- 组件镜像命名（按 docker-apim Dockerfile 的 server name，同一 docker hub org 下）：
  `wso2/wso2am-acp:4.7.0`、`wso2/wso2am-tm:4.7.0`、`wso2/wso2am-universal-gw:4.7.0`（镜像 tag 是否已全部推送未逐一在 Hub 页面验证——**部分未确认**，Dockerfile 已确认）
- 官方构建/运行（镜像内 JDK 实际为 Temurin 25，基础镜像 ubuntu:24.04）：
```bash
docker run -it -p 9443:9443 -p 8243:8243 wso2/wso2am:4.7.0
# 想映射网关 HTTP：再加 -p 8280:8280
```
首次启动健康检查接口：`http://localhost:9763/services/Version`。
来源：
- https://hub.docker.com/r/wso2/wso2am/tags （实测）
- https://github.com/wso2/docker-apim/blob/v4.7.0.2/dockerfiles/ubuntu/apim/README.md
- https://github.com/wso2/docker-apim/blob/v4.7.0.2/dockerfiles/ubuntu/apim/Dockerfile

### 4.2 docker-compose 样例仓库
- https://github.com/wso2/docker-apim （默认分支 master，最新 tag **v4.7.0.2**）
- 4.7 的 compose 模板（`docker-compose/` 下）：
  - `apim-with-analytics/`：APIM + analytics + MySQL 8.4.9；端口映射 `9443:9443 8280:8280 8243:8243`；APIM 配置通过 `./conf/apim` 挂载到 `/home/wso2carbon/wso2-config-volume`；MySQL 初始化脚本在 `./conf/mysql/scripts`
  - `apim-is-as-km-with-analytics/`（IS 做 Key Manager）
  - `apim-with-mi/`（带 Micro Integrator）
- 注意：**4.7 模板已没有早期版本里"单机 all-in-one 最简 compose"**，最简方式仍是上面单条 `docker run`。旧结构（4.5 及以前 `docker-compose/apim/`）可在对应 tag（如 v4.5.0.11、v4.6.0.x）里找到。
来源：https://github.com/wso2/docker-apim/tree/v4.7.0.2/docker-compose
容器内安装路径：`/home/wso2carbon/wso2am-4.7.0`，非 root 用户 wso2carbon(uid 10001) 运行。

---

## 5. 最小化 profile / 降内存

- **旧的 `-Dprofile=api-control-plane|gateway|traffic-manager` 单进程裁剪方式在 4.7 all-in-one 已移除**：v4.7.0 实际启动脚本 `api-manager.sh` 中 grep 不到任何 profile/optimize 处理（INSTALL.txt 里残留 `--optimize` 帮助文字，但脚本未实现——以脚本为准）。4.4–4.6 时代文档中的 profile 章节在 4.7 文档中已删除。
  来源：https://github.com/wso2/product-apim/blob/v4.7.0/all-in-one-apim/modules/distribution/product/src/main/startup-scripts/api-manager.sh
- 4.7 的"最小化"= **独立组件分发包**（仓库顶层就是这四个 Maven 聚合工程，release 各出 zip，docker-apim 各有 Dockerfile）：
  - `wso2am-acp`（API Control Plane：KM + Publisher + DevPortal）
  - `wso2am-tm`（Traffic Manager：限流/分析事件）
  - `wso2am-universal-gw`（Classic Gateway，Universal）
  - 分布式部署必须三者组网（+可选外部 KM/DB），不能像旧 profile 那样一个节点只加参数就瘦身。
  来源：
  - https://github.com/wso2/docs-apim/blob/master/en/docs/install-and-setup/setup/distributed-deployment/deploying-wso2-api-m-in-a-distributed-setup.md
  - https://github.com/wso2/product-apim/tree/v4.7.0
- **单机实验降内存的现实手段**：直接用 all-in-one + 调 JVM 堆（`bin/` 下的 heap 配置或 `JAVA_OPTS="-Xms512m -Xmx2g"`），H2 内嵌库零依赖；46G RAM 跑 all-in-one 完全够，不必上分布式。
- 门户 H2/dev 模式：若只改 React 前端，可用 apim-apps 的 dev server 指向本地后端，无需重打整个产品（apim-apps README 的开发工作流）。

---

## 6. 中国大陆网络环境的坑（结合本机实测）

本次调研环境本身就在大陆网络（IP 120.229.x.x），实测情况：

1. **GitHub 可达性不稳定但可用**
   - `raw.githubusercontent.com`、GitHub API、`codeload.github.com`（源码 tar.gz）实测可通；
   - `github.com` 的 git smart-HTTP（`git clone`）实测超时失败过一次；release 资源 302 跳转到 `release-assets.githubusercontent.com` 实测 HTTP 200 可下。
   - 对策：`git clone` 失败时改用 codeload 下 tar：`https://codeload.github.com/wso2/product-apim/tar.gz/refs/tags/v4.7.0`；产品 zip 走 release 直链；配 git 代理或用 ghproxy 类镜像加速（第三方，自行评估）。
2. **Maven 构建依赖是最大坑**
   - pom 写死了 `maven.wso2.org/nexus/...` 和 `dist.wso2.org/maven2`，这两个站大陆可访问但**慢且偶发断连**，且 WSO2 私有构件在阿里云等 Central 镜像里**没有**，不能简单全量 mirror 到 aliyun。
   - 推荐：`settings.xml` 只把 central 镜像到阿里云（`https://maven.aliyun.com/repository/public`），**保留 wso2-nexus 原样**；对 wso2 仓库走 HTTP(S) 代理（`mvn -Dhttps.proxyHost=...`）；用 `-Dmaven.test.skip=true` 减少集成测试阶段额外下载；失败重跑（Maven 断点续传/重跑基本能收敛）。
3. **Docker Hub**：`hub.docker.com` 本机直连 API 超时（浏览器方式可访问）；`docker pull wso2/wso2am:4.7.0` 需自备 registry 镜像加速或 Docker daemon 代理（2024 年后国内公共加速器大多失效）。绕开方案：
   - 直接下 GitHub release 的 zip（约数百 MB，走 GitHub release CDN，比 Docker Hub 成功率高）；
   - 或按 docker-apim 的 Dockerfile 本地 build（构建过程也是 wget GitHub release zip + apt/ubuntu 源 + adoptium GitHub 二进制，apt 可换国内源，JDK 来自 github.com/adoptium）。
4. **Node/npm（仅构建 apim-apps 时）**：Node 22/24 没问题；npm 仓换 npmmirror：`npm config set registry https://registry.npmmirror.com`。
5. **传统 wso2.com 下载站**：官网下载 zip 通常要走表单/302 到 `https://product-dist.wso2.com/...`，大陆访问质量一般；**优先用 GitHub release 直链**（Apache 2.0 GA 包同一产物）。
6. JDK：本机已有 JDK 21，无需额外安装；注意 `JAVA_HOME` 指向 21，且无 sudo 时在用户 shell rc 里 export 即可。

---

## 7. 推荐执行顺序（本机单机实验）

1. 零构建首选：
   ```bash
   wget -O wso2am-4.7.0.zip https://github.com/wso2/product-apim/releases/download/v4.7.0/wso2am-4.7.0.zip
   unzip wso2am-4.7.0.zip && cd wso2am-4.7.0/bin
   JAVA_HOME=/path/to/jdk-21 sh api-manager.sh
   # 浏览器打开 https://localhost:9443/publisher  admin/admin
   ```
2. 容器方式（解决 Docker Hub 网络后）：`docker run -it -p 9443:9443 -p 8280:8280 -p 8243:8243 wso2/wso2am:4.7.0`
3. 需要改源码再走 `mvn clean install -Dmaven.test.skip=true`（JDK 21 + Maven 3.9 + 配好 wso2 仓库代理），产物在 `all-in-one-apim/modules/distribution/product/target/wso2am-4.7.0.zip`。

## 主要来源汇总
- https://github.com/wso2/product-apim/releases
- https://github.com/wso2/product-apim/blob/v4.7.0/README.md
- https://github.com/wso2/product-apim/blob/v4.7.0/CONTRIBUTING.md
- https://github.com/wso2/product-apim/blob/v4.7.0/INSTALL.txt
- https://github.com/wso2/product-apim/blob/v4.7.0/pom.xml
- https://github.com/wso2/product-apim/blob/v4.7.0/all-in-one-apim/pom.xml
- https://github.com/wso2/apim-apps/blob/v9.3.194/README.md
- https://apim.docs.wso2.com/en/latest/ （渲染站有 Cloudflare 验证；等价内容取自 https://github.com/wso2/docs-apim ）
- https://github.com/wso2/docs-apim/blob/master/en/docs/reference/product-compatibility.md
- https://github.com/wso2/docs-apim/blob/master/en/docs/reference/default-product-ports.md
- https://github.com/wso2/docs-apim/blob/master/en/docs/install-and-setup/install/installation-prerequisites.md
- https://github.com/wso2/docs-apim/blob/master/en/docs/install-and-setup/install/installing-the-product/running-the-api-m.md
- https://github.com/wso2/docs-apim/blob/master/en/docs/install-and-setup/setup/distributed-deployment/deploying-wso2-api-m-in-a-distributed-setup.md
- https://hub.docker.com/r/wso2/wso2am/tags
- https://github.com/wso2/docker-apim/tree/v4.7.0.2
- https://github.com/wso2/docker-apim/blob/v4.7.0.2/docker-compose/apim-with-analytics/docker-compose.yml
