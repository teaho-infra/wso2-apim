"""WSO2 APIM Publisher v4 客户端:DCR 注册 → OAuth token → 读取已发布 API。"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import httpx


class Wso2Client:
    def __init__(self, cfg: dict, cache_path: str = ".wso2-cache.json"):
        self.base = cfg["base_url"].rstrip("/")
        self.username = cfg["username"]
        self.password = cfg["password"]
        self.status = cfg.get("lifecycle_status", "PUBLISHED")
        self.verify = cfg.get("verify_tls", False)
        self.default_upstream = cfg.get("default_upstream", {})
        self.cache_path = Path(cache_path)
        self.client_id = cfg.get("client_id") or ""
        self.client_secret = cfg.get("client_secret") or ""
        self._token = ""

    # ---------- DCR ----------
    def _basic_admin(self) -> str:
        raw = f"{self.username}:{self.password}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _load_cache(self) -> bool:
        if self.cache_path.exists():
            data = json.loads(self.cache_path.read_text())
            self.client_id = data.get("client_id", self.client_id)
            self.client_secret = data.get("client_secret", self.client_secret)
            return bool(self.client_id)
        return False

    def _save_cache(self) -> None:
        self.cache_path.write_text(json.dumps({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }, indent=2))

    def register(self) -> None:
        """Dynamic Client Registration(幂等:有缓存就复用)。"""
        if self.client_id or self._load_cache():
            return
        body = {
            "clientName": "wso2-adapter",
            "owner": self.username,
            "grantType": "password refresh_token",
            "saasApp": True,
        }
        r = httpx.post(
            f"{self.base}/client-registration/v0.17/register",
            headers={
                "Authorization": self._basic_admin(),
                "Content-Type": "application/json",
            },
            json=body, verify=self.verify, timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        self.client_id = data["clientId"]
        self.client_secret = data["clientSecret"]
        self._save_cache()

    # ---------- OAuth ----------
    def _token_basic(self) -> str:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def login(self) -> str:
        self.register()
        r = httpx.post(
            f"{self.base}/oauth2/token",
            headers={
                "Authorization": self._token_basic(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "password",
                "username": self.username,
                "password": self.password,
                "scope": "apim:api_view apim:api_create apim:api_publish",
            },
            verify=self.verify, timeout=30,
        )
        r.raise_for_status()
        self._token = r.json()["access_token"]
        return self._token

    def _auth(self) -> dict:
        if not self._token:
            self.login()
        return {"Authorization": f"Bearer {self._token}"}

    # ---------- Publisher v4 ----------
    def list_published_apis(self) -> list[dict]:
        r = httpx.get(
            f"{self.base}/api/am/publisher/v4/apis",
            headers=self._auth(),
            params={"limit": 100, "query": f"status:{self.status}"},
            verify=self.verify, timeout=30,
        )
        if r.status_code == 401:
            self.login()
            r = httpx.get(
                f"{self.base}/api/am/publisher/v4/apis",
                headers=self._auth(),
                params={"limit": 100, "query": f"status:{self.status}"},
                verify=self.verify, timeout=30,
            )
        r.raise_for_status()
        items = r.json().get("list", [])
        # 客户端侧精确复核:搜索索引在生命周期刚变更后可能有秒级延迟,
        # 以 DTO 实时字段 lifeCycleStatus 为准。
        return [a for a in items if a.get("lifeCycleStatus") == self.status]

    def get_api_detail(self, api_id: str) -> dict:
        r = httpx.get(
            f"{self.base}/api/am/publisher/v4/apis/{api_id}",
            headers=self._auth(), verify=self.verify, timeout=30,
        )
        r.raise_for_status()
        return r.json()
