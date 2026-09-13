"""演示上游服务:供 WSO2 APIM → SCG/Higress 路由转发的目标后端。

端点:
  GET /demo/echo     回显请求信息(method/path/headers/query)
  GET /demo/time     返回服务器时间
  GET /demo/headers  返回收到的请求头(验证网关是否透传/注入)
  GET /healthz       存活探针
监听 0.0.0.0:9081
"""
import datetime
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "9081"))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send(200, {"status": "ok"})
        elif path == "/demo/echo":
            self._send(200, {
                "service": "downstream",
                "method": "GET",
                "path": self.path,
                "query_echo": "received",
                "headers": {k: v for k, v in self.headers.items()},
            })
        elif path == "/demo/time":
            self._send(200, {
                "service": "downstream",
                "server_time": datetime.datetime.now().astimezone().isoformat(),
                "epoch_ms": int(datetime.datetime.now().timestamp() * 1000),
            })
        elif path == "/demo/headers":
            self._send(200, {
                "service": "downstream",
                "headers": {k: v for k, v in self.headers.items()},
            })
        else:
            self._send(404, {"error": "not found", "path": path})

    def log_message(self, format, *args):  # noqa: A002 (base signature)
        # 简洁日志
        print(f"[downstream] {self.address_string()} - {format % args}", flush=True)


if __name__ == "__main__":
    print(f"[downstream] listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
