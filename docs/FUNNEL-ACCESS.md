# 经 Tailscale Funnel 公网访问 WSO2 三个管理台

把本机源码版 WSO2 APIM 4.7（`:9543`）通过用户级 nginx（`:8443`）挂到 Tailscale
Funnel 公网 443，供浏览器访问 Carbon / Publisher / DevPortal。

## 链路与双层认证

```
浏览器 → https://<tailnet-host>/  (Tailscale Funnel TLS 终止, 443)
       → 本机 tailscaled → 127.0.0.1:8443 (用户级 nginx)
            第 1 层:HTTP Basic(htpasswd-wso2,独立强口令)
       → proxy_pass https://127.0.0.1:9543 (WSO2,自签,proxy_ssl_verify off)
            第 2 层:WSO2 自身登录(admin / 强口令,已改)
```

- Funnel 域名：`https://leonbook5-jiguang-series.tailb1426a.ts.net`
- 入口：`/wso2`(→Publisher)、`/publisher/`、`/devportal/`、`/carbon/`
- 两道口令**分别保存、互不同**；外层 Basic 头在回源时用 `map` 剥掉 `Basic`、
  保留 SPA 的 `Bearer`，避免把外层凭据误当 WSO2 凭据。

## 为什么不能简单挂 `/wso2` 子前缀

WSO2 门户用的是绝对根路径（`/carbon`、`/publisher`、`/api/am/*`、`/oauth2`…），
挂单一子前缀会让前端静态资源与 API 全部 404。因此按 webapp 上下文逐个 `location ^~`
反代（见 `wso2-locations.conf`），`/wso2` 仅作跳转入口。
`/api/am/`、`/api/identity/` 精确切给 WSO2，其余 `/api/` 仍归同机 multica。

## 关键：localhost 写死地址的改写

Publisher/DevPortal 是 React SPA，运行配置 `settings.js` 与
`/oauth2/oidcdiscovery/.well-known/openid-configuration` 会把
`issuer`、`authorization_endpoint`、`checkSessionEndpoint` 等写死成
`https://localhost:9543`，公网浏览器无法用。实测：

- 改 Tomcat connector 的 `proxyName/proxyPort`、`[server].mgt_console_hostname`、
  `identity.auth_framework.identity_server_origin` **都不生效或有副作用**
  （issuer/IdPEntityId 首次启动已持久化，且改 identity origin 会引发内部
  `/internal/data/v1` SSL 调用错误）。
- 采用 **nginx 响应改写**，WSO2 内部完全保持 `localhost`，零副作用：
  - `sub_filter` 把响应体（`application/javascript`、`application/json`）里的
    `https://localhost:9543` / `:443` / `https://localhost` 替换为公网 `$host`；
    并清空 `Accept-Encoding` 防止 gzip 导致无法改写。
  - `proxy_redirect` 用正则改写 302 `Location` 里的 `localhost[:port]`。

## 相关文件（在仓库之外，本机路径）

- `~/.local/nginx/conf/nginx.conf`：server 段 include `wso2-locations.conf`；
  http 段的 `map $http_authorization $wso2_upstream_auth`
- `~/.local/nginx/conf/wso2-locations.conf`：WSO2 各 webapp 前缀
- `~/.local/nginx/conf/wso2-proxy.inc`：回源 + Basic + sub_filter/proxy_redirect
- `~/.local/nginx/conf/htpasswd-wso2`（600）：外层 Basic
- 口令明文暂存（600）：`~/.local/nginx/conf/.wso2-funnel-password`（外层）、
  `.wso2-admin-password`（WSO2 admin）——不要提交、分享后可删。

重载：`~/bin/nginx -c ~/.local/nginx/conf/nginx.conf -t &&
~/bin/nginx -c ~/.local/nginx/conf/nginx.conf -s reload`

## 改 WSO2 admin 口令（4.7）

`bin/chpasswd.sh` 在 4.7 依赖 `ant` 且类路径缺失，直接用其底层类直连 H2
（服务需停止；UM 表在 WSO2SHARED_DB）：

```bash
RT=<CARBON_HOME>; NEWPW='...'
java -cp "lib/*:repository/components/plugins/*:bin/org.wso2.carbon.bootstrap-4.11.18.jar" \
  -Dcarbon.home="$RT" org.wso2.carbon.core.util.PasswordUpdater \
  --db-url "jdbc:h2:file:$RT/repository/database/WSO2SHARED_DB" \
  --db-driver org.h2.Driver --db-username wso2carbon --db-password wso2carbon \
  --username admin --new-password "$NEWPW"
```

注意：直接删空 H2 文件不会自动建表，需 `-Dsetup` 且一次性初始化（Andes/MB 库
容易因残留文件初始化失败）。生产建议外部数据库。

## 验证清单

| 检查 | 期望 |
|---|---|
| 公网无凭证访问 `/publisher/` | 401 |
| 外层 Basic 后三控制台 | 200 |
| Carbon `login_action.jsp` 正确/错误口令 | `loginStatus=true` / `=false` |
| 公网 OIDC discovery / settings.js | 主机名全部为公网域名，无 localhost |
| `/oidc/checksession`、SPA bundle | 200 |
| `/health`、multica `/api/*` | 不受影响 |

> 公网暴露面：Funnel 已能被互联网扫描器探测到。双层认证中任一弱口令即失守；
> 生产请加强密码、限制来源（Tailscale Serve 仅 tailnet，或 IP allowlist）并启用审计。
