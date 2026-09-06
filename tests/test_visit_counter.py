import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "counter"))

from visit_counter import CountStore, RateLimiter, create_server  # noqa: E402


class CountStoreTests(unittest.TestCase):
    def test_increment_persists_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            store = CountStore(data_dir)
            self.assertEqual(store.visitors(), 0)
            self.assertEqual(store.increment(), 1)
            self.assertEqual(store.increment(), 2)
            reloaded = CountStore(data_dir)  # 模拟服务重启
            self.assertEqual(reloaded.visitors(), 2)

    def test_corrupt_file_starts_at_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            (data_dir / "count.json").write_text("not-json", encoding="utf-8")
            self.assertEqual(CountStore(data_dir).visitors(), 0)

    def test_non_positive_file_value_clamped_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            (data_dir / "count.json").write_text('{"visitors": -5}', encoding="utf-8")
            self.assertEqual(CountStore(data_dir).visitors(), 0)


class RateLimiterTests(unittest.TestCase):
    def test_same_key_blocked_within_window(self) -> None:
        limiter = RateLimiter(10)
        self.assertTrue(limiter.allow("1.2.3.4"))
        self.assertFalse(limiter.allow("1.2.3.4"))

    def test_different_keys_independent(self) -> None:
        limiter = RateLimiter(10)
        self.assertTrue(limiter.allow("1.1.1.1"))
        self.assertTrue(limiter.allow("2.2.2.2"))

    def test_window_expires(self) -> None:
        limiter = RateLimiter(0.05)
        self.assertTrue(limiter.allow("k"))
        time.sleep(0.08)
        self.assertTrue(limiter.allow("k"))


class _Server:
    """在临时端口上起一个真实服务实例，供 HTTP 集成测试。"""

    def __init__(self, rate_limit_seconds: float = 10.0) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.srv = create_server("127.0.0.1", 0, Path(self._tmp.name), rate_limit_seconds)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=2)
        self._tmp.cleanup()


class VisitCounterHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _Server()
        self.addCleanup(self.server.close)

    def _request(self, method: str, cookie: str | None = None, forwarded_for: str | None = None,
                 cf_ip: str | None = None, path: str = "/count"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        headers = {}
        if cookie:
            headers["Cookie"] = cookie
        if forwarded_for:
            headers["X-Forwarded-For"] = forwarded_for
        if cf_ip:
            headers["CF-Connecting-IP"] = cf_ip
        conn.request(method, path, headers=headers)
        resp = conn.getresponse()
        body = json.loads(resp.read().decode("utf-8"))
        set_cookie = resp.getheader("Set-Cookie")
        conn.close()
        return body, set_cookie

    def test_get_is_read_only(self) -> None:
        for _ in range(3):
            body, set_cookie = self._request("GET")
            self.assertEqual(body["visitors"], 0)
            self.assertIsNone(set_cookie)

    def test_first_post_counts_and_sets_cookie(self) -> None:
        body, set_cookie = self._request("POST")
        self.assertEqual(body["visitors"], 1)
        self.assertIsNotNone(set_cookie)
        self.assertIn("csbaoyan_vid=", set_cookie)
        self.assertIn("SameSite=Lax", set_cookie)
        self.assertIn("HttpOnly", set_cookie)

    def test_cookie_visitor_not_recounted(self) -> None:
        """核心口径：同一读者刷新/重访不加数。"""
        _, set_cookie = self._request("POST")
        cookie = set_cookie.split(";", 1)[0]  # csbaoyan_vid=<uuid>
        for _ in range(3):
            body, resp_cookie = self._request("POST", cookie=cookie)
            self.assertEqual(body["visitors"], 1)
            self.assertIsNone(resp_cookie)  # 老读者不再下发 cookie

    def test_forged_cookie_does_not_double_count(self) -> None:
        """伪造/非法 cookie 在限流窗口内不加数（防脚本刷量）。"""
        body, _ = self._request("POST")
        self.assertEqual(body["visitors"], 1)
        body, _ = self._request("POST", cookie="csbaoyan_vid=not-a-uuid")
        self.assertEqual(body["visitors"], 1)

    def test_rate_limit_blocks_repeated_cookieless_posts(self) -> None:
        body, _ = self._request("POST")
        self.assertEqual(body["visitors"], 1)
        body, _ = self._request("POST")  # 不带 cookie 连发（如 curl）不加数
        self.assertEqual(body["visitors"], 1)

    def test_distinct_visitors_counted(self) -> None:
        body, _ = self._request("POST", forwarded_for="9.9.9.9")
        self.assertEqual(body["visitors"], 1)
        body, _ = self._request("POST", forwarded_for="8.8.8.8")
        self.assertEqual(body["visitors"], 2)

    def test_api_count_path_accepted(self) -> None:
        """cloudflared 不改写路径：前端请求 /api/count 必须直达。"""
        body, set_cookie = self._request("POST", cf_ip="7.7.7.7", path="/api/count")
        self.assertEqual(body["visitors"], 1)
        self.assertIsNotNone(set_cookie)
        body, _ = self._request("GET", path="/api/count")
        self.assertEqual(body["visitors"], 1)

    def test_cf_connecting_ip_preferred_for_rate_limit(self) -> None:
        """CF-Connecting-IP 是 cloudflared 的权威访客 IP：不同访客不受彼此限流。"""
        body, _ = self._request("POST", cf_ip="5.5.5.5", forwarded_for="7.7.7.7")
        self.assertEqual(body["visitors"], 1)
        body, _ = self._request("POST", cf_ip="6.6.6.6", forwarded_for="7.7.7.7")
        self.assertEqual(body["visitors"], 2)

    def test_unknown_path_returns_404(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        conn.request("GET", "/admin")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)
        conn.close()


if __name__ == "__main__":
    unittest.main()
