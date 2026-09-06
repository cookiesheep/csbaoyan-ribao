#!/usr/bin/env python3
"""保研日报 · 独立读者计数器（发行量）

零依赖（纯标准库）的独立访客计数服务：

- POST /count —— 无有效 cookie 的请求：下发一年期 cookie 并 +1；
  已有 cookie 的请求：只返回当前总数，不重复计数。
- GET /count —— 只读当前总数。
- 计数落盘到 <data-dir>/count.json（临时文件 + 原子替换）。
- 同一来源 IP 在限流窗口内（默认 10 秒）至多计 1 次，防止脚本刷量。

不记录 IP、UA 或任何可识别信息；落盘文件里只有一个整数。
部署说明见同目录 README.md。
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

COOKIE_NAME = "csbaoyan_vid"
COOKIE_MAX_AGE = 31536000  # 一年
COUNT_FILENAME = "count.json"


class CountStore:
    """计数落盘：count.json，原子替换写入。"""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / COUNT_FILENAME
        self._lock = threading.Lock()
        self._visitors = self._load()

    def _load(self) -> int:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return max(0, int(data["visitors"]))
        except (OSError, ValueError, KeyError, TypeError):
            return 0

    def visitors(self) -> int:
        with self._lock:
            return self._visitors

    def increment(self) -> int:
        with self._lock:
            self._visitors += 1
            self._save()
            return self._visitors

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"visitors": self._visitors}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


class RateLimiter:
    """同一 key 在窗口内只放行一次；内存字典，重启即清空。"""

    def __init__(self, window_seconds: float) -> None:
        self.window = window_seconds
        self._lock = threading.Lock()
        self._last_seen: dict[str, float] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last_seen.get(key)
            if last is not None and now - last < self.window:
                return False
            self._last_seen[key] = now
            if len(self._last_seen) > 8192:  # 防内存膨胀：超限裁剪过期项
                cutoff = now - self.window
                self._last_seen = {k: ts for k, ts in self._last_seen.items() if ts >= cutoff}
            return True


def build_set_cookie(value: str, secure: bool) -> str:
    parts = [
        f"{COOKIE_NAME}={value}",
        f"Max-Age={COOKIE_MAX_AGE}",
        "Path=/",
        "SameSite=Lax",
        "HttpOnly",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def parse_visitor_cookie(header: str | None) -> str | None:
    """从 Cookie 头里取合法的访客 id；没有或非法返回 None。"""
    if not header:
        return None
    try:
        jar = SimpleCookie()
        jar.load(header)
    except CookieError:
        return None
    morsel = jar.get(COOKIE_NAME)
    if morsel is None:
        return None
    try:
        return str(uuid.UUID(morsel.value))
    except (ValueError, AttributeError):
        return None


def create_handler(store: CountStore, limiter: RateLimiter):
    class VisitorCounterHandler(BaseHTTPRequestHandler):
        server_version = "BaoyanCounter/1.0"
        protocol_version = "HTTP/1.1"

        # ---- 基础应答 ----
        def _send_json(self, status: int, payload: dict, set_cookie: str | None = None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            if set_cookie:
                self.send_header("Set-Cookie", set_cookie)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # ---- 请求上下文 ----
        def _client_key(self) -> str:
            # 仅在反代后使用：nginx 用 $remote_addr 覆盖此头，不可伪造
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
            return self.client_address[0] if self.client_address else "unknown"

        def _is_https(self) -> bool:
            # 反代会带上 X-Forwarded-Proto: https，此时 cookie 附加 Secure
            return self.headers.get("X-Forwarded-Proto", "").strip().lower() == "https"

        # ---- 路由 ----
        def do_GET(self) -> None:  # 只读
            if self.path.split("?", 1)[0] != "/count":
                self._send_json(404, {"error": "not found"})
                return
            self._send_json(200, {"visitors": store.visitors()})

        def do_POST(self) -> None:
            if self.path.split("?", 1)[0] != "/count":
                self._send_json(404, {"error": "not found"})
                return
            if parse_visitor_cookie(self.headers.get("Cookie")):
                # 老读者：只读数，不动计数
                self._send_json(200, {"visitors": store.visitors()})
                return
            # 无有效 cookie：发新 id；限流窗口内不重复计数
            if limiter.allow(self._client_key()):
                total = store.increment()
            else:
                total = store.visitors()
            cookie = build_set_cookie(str(uuid.uuid4()), secure=self._is_https())
            self._send_json(200, {"visitors": total}, set_cookie=cookie)

    return VisitorCounterHandler


def create_server(host: str, port: int, data_dir: Path, rate_limit_seconds: float) -> ThreadingHTTPServer:
    store = CountStore(data_dir)
    limiter = RateLimiter(rate_limit_seconds)
    return ThreadingHTTPServer((host, port), create_handler(store, limiter))


def main() -> None:
    parser = argparse.ArgumentParser(description="保研日报独立读者计数器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1，仅反代可见）")
    parser.add_argument("--port", type=int, default=8001, help="监听端口（默认 8001）")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "data",
        help="计数文件目录（默认 <脚本目录>/data）",
    )
    parser.add_argument(
        "--rate-limit-seconds",
        type=float,
        default=10.0,
        help="同一 IP 两次计数之间的最小间隔秒数（默认 10）",
    )
    args = parser.parse_args()

    server = create_server(args.host, args.port, args.data_dir, args.rate_limit_seconds)
    print(f"visit_counter listening on {args.host}:{args.port}, data={args.data_dir}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
