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

log() { echo "$@" >&2; }
log "▶️  WSO2 base = $BASE"

# 1) DCR(复用缓存)
if [ -f "$CACHE" ]; then
  CID=$(python3 -c "import json;print(json.load(open('$CACHE'))['clientId'])")
  CSEC=$(python3 -c "import json;print(json.load(open('$CACHE'))['clientSecret'])")
  log "• 复用 DCR client: $CID"
else
  log "• 注册 DCR client ..."
  RESP=$($CURL -X POST "$BASE/client-registration/v0.17/register" \
    -u "$ADMIN_USER:$ADMIN_PASS" -H 'Content-Type: application/json' \
    -d '{"clientName":"wso2-adapter-cli","owner":"'$ADMIN_USER'","grantType":"password refresh_token","saasApp":true}')
  CID=$(echo "$RESP" | python3 -c "import json,sys;print(json.load(sys.stdin)['clientId'])")
  CSEC=$(echo "$RESP" | python3 -c "import json,sys;print(json.load(sys.stdin)['clientSecret'])")
  echo "{\"clientId\":\"$CID\",\"clientSecret\":\"$CSEC\"}" > "$CACHE"
fi

# 2) token
TOKEN=$($CURL -X POST "$BASE/oauth2/token" \
  -u "$CID:$CSEC" -H 'Content-Type: application/x-www-form-urlencoded' \
  -d "grant_type=password&username=$ADMIN_USER&password=$ADMIN_PASS&scope=apim:api_view apim:api_create apim:api_publish" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
log "• token 获取成功 (${#TOKEN} chars)"
AUTH="Authorization: Bearer $TOKEN"

# 创建(若重名则查出现有 id),echo 只输出 id
ensure_api() {
  local name="$1" context="$2"
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
  # Publisher v4: endpointConfig 必须是 JSON 对象(不是字符串),否则 ClassCastException
  "endpointConfig": {
    "endpoint_type": "http",
    "sandbox_endpoints": {"url": "http://downstream:9081"},
    "production_endpoints": {"url": "http://downstream:9081"}
  },
}))
PY
)
  log "• 创建 API: $name ($context)"
  local resp id
  resp=$($CURL -X POST "$BASE/api/am/publisher/v4/apis" -H "$AUTH" \
    -H 'Content-Type: application/json' -d "$body")
  id=$(echo "$resp" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('id',''))" 2>/dev/null || echo "")
  if [ -z "$id" ]; then
    log "  已存在或失败,按 name 查询。响应: $(echo "$resp" | head -c 160)"
    id=$($CURL "$BASE/api/am/publisher/v4/apis?limit=100" -H "$AUTH" \
      | NAME="$name" python3 -c "import json,os,sys;d=json.load(sys.stdin);n=os.environ['NAME'];print(next((a['id'] for a in d.get('list',[]) if a['name']==n),''))" 2>/dev/null || echo "")
  fi
  echo "$id"
}

publish() {
  local id="$1"
  local status
  status=$($CURL -o /dev/null -w '%{http_code}' -X POST \
    "$BASE/api/am/publisher/v4/apis/change-lifecycle?action=Publish&apiId=$id" -H "$AUTH")
  log "  Publish $id -> HTTP $status"
}

ECHO_ID=$(ensure_api DemoEchoAPI /demo/echo)
TIME_ID=$(ensure_api DemoTimeAPI /demo/time)
log "echo id=$ECHO_ID ; time id=$TIME_ID"
[ -n "$ECHO_ID" ] && publish "$ECHO_ID"
[ -n "$TIME_ID" ] && publish "$TIME_ID"

log "• 当前 API:"
$CURL "$BASE/api/am/publisher/v4/apis?limit=20" -H "$AUTH" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);[print('  -',a['name'],a.get('context'),a.get('version'),a.get('lifeCycleStatus')) for a in d.get('list',[])]" >&2
