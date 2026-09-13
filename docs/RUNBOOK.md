# 运行手册（RUNBOOK）

把 WSO2 APIM 4.7 Publisher 中已发布的 API，通过一个外部 reconcile adapter
对账下发到 **Spring Cloud Gateway 4.3** 与 **Higress** 两个数据面。

```
WSO2 APIM 4.7 (Publisher v4 REST)
        │  DCR + OAuth, 轮询 PUBLISHED API
        ▼
  wso2_adapter (Python)          统一模型 Route/Upstream
   ┌──────┴───────┐
   ▼              ▼
SCG 4.3        Higress (Envoy)
actuator       标准 Ingress (docker cp / kubectl)
   └──────┬───────┘
          ▼
   downstream demo :9081 (/demo/echo /demo/time /demo/headers)
```

## 0. 组件与端口

| 组件 | 形态 | 端口 |
|---|---|---|
| WSO2 APIM 4.7 | 源码产物，JDK21 进程，offset=100 | https **9543**（carbon/publisher/devportal）、网关 8343/8380 |
| SCG 4.3 | docker 容器 `wso2-demo-scg` | http **9080**（actuator 写端点已开） |
| Higress | 本机 all-in-one 容器 `higress` | console 18001、网关 **18080**（http）/18443 |
| downstream | docker 容器 `wso2-demo-downstream` | http **9081** |

凭据为产品默认 `admin/admin`（仅本机演示，勿用于生产）。

## 1. 从源码构建 WSO2 APIM（产物已在本机）

```bash
cd infra/wso2-apim
curl -sL --proxy http://127.0.0.1:7890 -o product-apim-4.7.0.tar.gz \
  https://codeload.github.com/wso2/product-apim/tar.gz/refs/tags/v4.7.0
tar xzf product-apim-4.7.0.tar.gz
cd product-apim-4.7.0
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 MAVEN_OPTS="-Xmx4g"
/home/leonbook5/soft/maven/apache-maven-3.8.2/bin/mvn clean install \
  -Dmaven.test.skip=true -Dmaven.javadoc.skip=true -B \
  -Dmaven.wagon.http.retryHandler.count=3 -Dmaven.wagon.http.readTimeout=60000 \
  -Dhttp.keepAlive=false -Dmaven.wagon.http.pool=false \
  -s ../../maven-settings.xml
# 产品产物(itests 失败不影响):
# all-in-one-apim/modules/distribution/product/target/wso2am-4.7.0.zip
unzip -t <zip>   # 先校验完整性
```

## 2. 启动 WSO2（9543）

```bash
bash scripts/start-apim-from-build.sh        # 解压到 infra/wso2-apim/runtime,加 offset=100,前台启动
# 成功标志:wso2carbon.log 出现 "WSO2 Carbon started in N sec"
curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1:9543/carbon/   # 302
```

## 3. 起两个数据面

```bash
cd infra
docker compose up -d --build
docker compose ps        # scg / downstream 均 healthy
curl -s http://127.0.0.1:9081/demo/time      # downstream 直连
```

## 4. 在 WSO2 发布 2 个 demo API

```bash
WSO2_PORT=9543 bash scripts/02-publish-demo-apis.sh
# 幂等:重名(900300)时自动查出 id 再 Publish
# 末行应见 DemoEchoAPI /demo/time 1.0.0 PUBLISHED 两条
```

## 5. adapter 对账下发

```bash
cd adapter
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.local.yaml    # 已随仓库提供本机版
PYTHONPATH=src python -m wso2_adapter.main --config config.local.yaml diff    # 查看增/删
PYTHONPATH=src python -m wso2_adapter.main --config config.local.yaml sync    # 下发双网关
# 常驻轮询: ... loop
```

## 6. 端到端验证（发布 → 下线 → 恢复）

```bash
for p in /demo/echo /demo/time; do
  echo "SCG  $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9080$p)"
  echo "HIG  $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080$p)"
done    # 全部 200

# 下线(PUBLISHED -> Created)
WSO2_PORT=9543 bash scripts/03-set-lifecycle.sh "Demote to Created"
PYTHONPATH=src python -m wso2_adapter.main --config config.local.yaml sync
# 四个路径全部 404

# 恢复
WSO2_PORT=9543 bash scripts/03-set-lifecycle.sh Publish
PYTHONPATH=src python -m wso2_adapter.main --config config.local.yaml sync
# 四个路径回到 200
```

实测证据：`evidence/task6-e2e-lifecycle.{md,json}`。

## 关键设计约束

- **只纳管自有资源**：SCG 路由 id / Higress Ingress 名均带 `wso2-` 前缀，
  绝不删除人工或系统资源（Higress 的 `default.yaml`、`higress-gateway` 不动）。
- **SCG**：更新先 DELETE 再 POST，最后 `POST /actuator/gateway/refresh`。
- **Higress**：渲染标准 networking.k8s.io/v1 Ingress + 共享 Service/Endpoints，
  `docker cp` 进 all-in-one 的 `/data/...`（docker cp 是 merge 语义，stale 文件
  需单独 `docker exec rm`，本地 tmp 每次清空）。Endpoints 指 docker0 `172.17.0.1:9081`。
- 上游地址仅为 WSO2 侧声明值；APIM 本身无需网络可达 downstream，转发由两个网关完成。

## 清理

```bash
cd infra && docker compose down
# 停 WSO2: 杀 bin/api-manager.sh 的 java 进程;产物在 infra/wso2-apim/runtime(已 gitignore)
# Higress 内残留: docker exec higress rm -f /data/{ingresses,services,endpoints}/wso2-*.yaml
```

## 已知边界

- APIM 内置 H2、all-in-one 单节点，仅为演示；生产应外部 DB + 分 profile。
- Higress 当前复用本机 HiMarket 的 all-in-one 容器；要完全隔离可另起一个独立实例。
- AMQP 实时事件未接，adapter 用轮询（默认 10s）；后续可加 JMS 订阅做准实时。
- SCG 路由为内存态，网关重启后需再跑一次 `sync` 回填。
