#!/usr/bin/env bash
# Task 2: 对 WSO2 APIM 走 REST 完成 DCR → OAuth → 建 2 个 demo API → Publish。
# 默认对接源码构建产物(offset=100,管理口 9543);镜像版用 WSO2_PORT=9443。
set -euo pipefail

WSO2_HOST="${WSO2_HOST:-127.0.0.1}"
WSO2_PORT="${WSO2_PORT:-9543}"
BASE="https://${WSO2_HOST}:${WSO2_PORT}"
ADMIN_USER="${WSO2_USER:-admin}"
ADMIN_PASS="${WSO2_PASS:-admin}"
CACHE="${CACHE:-/tmp/wso2-dcr.json}"
CURL="curl -sk --max-time 20"

echo "▶️  WSO2 base = $BASE"

# 1) DCR(复用缓存)
if [ -f "$CACHE" ]; then
  CID=$(python3 -c "import json;print(json.load(open('$CACHE'))['clientId'])")
  CSEC=$(python3 -c "import json;print(json.load(open('$CACHE'))['clientSecret'])")
  echo "• 复用 DCR client: $CID"
else
  echo "• 注册 DCR client ..."
  RESP=$($CURL -X POST "$BASE/client-registration/v0.17/register" \
    -u "$ADMIN_USER:$ADMIN_PASS" -H 'Content-Type: application/json' \
    -d '{"clientName":"wso2-adapter-cli","owner":"'$ADMIN_USER'","grantType":"password refresh_token","saasApp":true}')
  echo "$RESP" > "$CACHE.raw"
  CID=$(echo "$RESP" | python3 -c "import json,sys;print(json.load(sys.stdin)['clientId'])")
  CSEC=$(echo "$RESP" | python3 -c "import json,sys;print(json.load(sys.stdin)['clientSecret'])")
  echo "{\"clientId\":\"$CID\",\"clientSecret\":\"$CSEC\"}" > "$CACHE"
fi

# 2) token
TOKEN=$($CURL -X POST "$BASE/oauth2/token" \
  -u "$CID:$CSEC" -H 'Content-Type: application/x-www-form-urlencoded' \
  -d "grant_type=password&username=$ADMIN_USER&password=$ADMIN_PASS&scope=apim:api_view apim:api_create apim:api_publish" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
echo "• token 获取成功 (${#TOKEN} chars)"
AUTH="Authorization: Bearer $TOKEN"

create_api() {
  local name="$1" context="$2"
  echo "• 创建 API: $name ($context)"
  local body
  body=$(python3 - "$name" "$context" <<'PY'
import json,sys
name,context=sys.argv[1],sys.argv[2]
print(json.dumps({
  "name": name,
  "description": f"Demo API for {context} (wso2-adapter e2e)",
  "context": context,
  "version": "1.0.0",
  "isDefaultVersion": True,
  "transport": ["http","https"],
  "visibility": "PUBLIC",
  "policies": ["Unlimited"],
  "operations": [
    {"target":"/","verb":"GET","throttlingPolicy":"Unlimited","authType":"None"},
  ],
  "endpointConfig": json.dumps({
    "endpoint_type":"http",
    "sandbox_endpoints":{"sandbox_default":"http://downstream:9081"},
    "production_endpoints":{"sandbox_default":"http://downstream:9081"}
  }),
}))
PY
)
  $CURL -X POST "$BASE/api/am/publisher/v4/apis" -H "$AUTH" \
    -H 'Content-Type: application/json' -d "$body"
}

# 3) 建 2 个 API(若已存在会返回 409,不致命)
create_api "DemoEchoAPI" "/demo/echo" >/tmp/api-echo.json; echo
create_api "DemoTimeAPI" "/demo/time" >/tmp/api-time.json; echo

# 4) Publish
for f in /tmp/api-echo.json /tmp/api-time.json; do
  ID=$(python3 -c "import json;print(json.load(open('$f')).get('id',''))" 2>/dev/null || echo "")
  if [ -n "$ID" ]; then
    echo "• Publish $ID"
    $CURL -X POST "$BASE/api/am/publisher/v4/apis/change-lifecycle?action=Publish&apiId=$ID" \
      -H "$AUTH" -o /dev/null -w "  lifecycle: %{http_code}\n"
  else
    echo "⚠️  $f 无 id(可能已存在或建失败),内容: $(head -c200 $f)"
  fi
done

# 5) 列出 PUBLISHED
echo "• 当前 PUBLISHED API:"
$CURL "$BASE/api/am/publisher/v4/apis?limit=20" -H "$AUTH" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);[print('  -',a['name'],a.get('context'),a.get('lifeCycleStatus')) for a in d.get('list',[])]"
