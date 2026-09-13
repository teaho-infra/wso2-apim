#!/usr/bin/env bash
# Task 6 辅助:切换两个 demo API 的生命周期状态,配合 adapter sync 验证增/删收敛。
#   bash scripts/03-set-lifecycle.sh Publish               # 重新发布
#   bash scripts/03-set-lifecycle.sh "Demote to Created"   # 下线(带空格,需引号)
set -euo pipefail
WSO2_PORT="${WSO2_PORT:-9543}"
ACTION="${1:-Publish}"
export WSO2_PORT ACTION

python3 - <<'PY'
import os, subprocess, json, sys
base = f"https://127.0.0.1:{os.environ['WSO2_PORT']}"
action = os.environ["ACTION"]
cache = json.load(open(os.environ.get("CACHE", "/tmp/wso2-dcr.json")))
import urllib.parse, urllib.request, ssl
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def post_form(url, data, auth=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
    req.add_header("Content-Type","application/x-www-form-urlencoded")
    if auth: req.add_header("Authorization",auth)
    return urllib.request.urlopen(req, context=ctx, timeout=20)
def get(url, auth):
    req=urllib.request.Request(url); req.add_header("Authorization",auth)
    return json.load(urllib.request.urlopen(req,context=ctx,timeout=20))
def post(url, auth):
    req=urllib.request.Request(url, method="POST"); req.add_header("Authorization",auth)
    try:
        return urllib.request.urlopen(req,context=ctx,timeout=20).status
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.read().decode()[:160]}"

tok = json.load(post_form(f"{base}/oauth2/token",
    {"grant_type":"password","username":"admin","password":"admin",
     "scope":"apim:api_view apim:api_publish"},
    auth="Basic "+__import__("base64").b64encode(f"{cache['clientId']}:{cache['clientSecret']}".encode()).decode()))["access_token"]
auth="Bearer "+tok
apis = get(f"{base}/api/am/publisher/v4/apis?limit=100", auth)["list"]
for a in apis:
    if a["name"].startswith("Demo"):
        q = urllib.parse.urlencode({"action":action,"apiId":a["id"]})
        print(action, "|", a["name"], "->", post(f"{base}/api/am/publisher/v4/apis/change-lifecycle?{q}", auth))
PY
