from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
import threading
import unittest

from shopping_demo.web import BODY_LIMIT, COOKIE_NAME, DemoServer


class LocalWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DemoServer(("127.0.0.1", 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host = cls.server.allowed_host
        cls.origin = cls.server.allowed_origin

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, *, body=None, headers=None, cookie=None, csrf=None):
        options = {"Host": self.host}
        if cookie:
            options["Cookie"] = cookie
        if csrf:
            options["X-CSRF-Token"] = csrf
        if body is not None:
            if not isinstance(body, (bytes, str)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            options["Content-Type"] = "application/json"
        options.update(headers or {})
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=options)
            response = conn.getresponse()
            data = response.read()
            info = dict(response.getheaders())
            if response.getheader("Content-Type", "").startswith("application/json"):
                data = json.loads(data)
            return response.status, data, info
        finally:
            conn.close()

    def session(self):
        code, data, headers = self.request("GET", "/api/session")
        self.assertEqual(code, 200)
        return data, headers["Set-Cookie"].split(";", 1)[0]

    def test_static_ui_has_explicit_non_llm_disclaimer(self):
        code, data, headers = self.request("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn("离线脚本演示 · 非 LLM · 不真实购物", data.decode())
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_only_loopback_binding_allowed(self):
        with self.assertRaises(ValueError):
            DemoServer(("0.0.0.0", 0))

    def test_cookie_is_http_only_and_same_site_strict(self):
        code, data, headers = self.request("GET", "/api/session")
        self.assertEqual(code, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertNotIn(COOKIE_NAME, json.dumps(data))

    def test_foreign_host_and_origin_rejected(self):
        for headers in ({"Host": "attacker.invalid"}, {"Host": "localhost:" + str(self.server.server_port)},
                        {"Origin": "https://attacker.invalid"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("GET", "/api/session", headers=headers)[0], 403)

    def test_same_origin_browser_request_works(self):
        code, _, _ = self.request("GET", "/api/session", headers={"Origin": self.origin, "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(code, 200)

    def test_path_traversal_and_arbitrary_url_rejected(self):
        for path in ("/../DEMO_README.md", "/%2e%2e/DEMO_README.md", "/%252e%252e/DEMO_README.md",
                     "/..%5cDEMO_README.md", "/%00", "http://attacker.invalid/", "http://[bad"):
            with self.subTest(path=path):
                code, _, _ = self.request("GET", path)
                self.assertEqual(code, 400)
        for path in ("/DEMO_README.md", "/prototype/purchase_guard.py", "/api/fetch?url=https://example.com", "/static/"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_state_requires_an_existing_session(self):
        self.assertEqual(self.request("GET", "/api/state")[0], 401)
        self.assertEqual(self.request("GET", "/api/state", cookie=COOKIE_NAME + "=invented")[0], 401)

    def test_mutation_requires_session_and_csrf(self):
        data, cookie = self.session()
        self.assertEqual(self.request("POST", "/api/run", body={})[0], 401)
        self.assertEqual(self.request("POST", "/api/run", body={}, cookie=cookie)[0], 403)
        self.assertEqual(self.request("POST", "/api/run", body={}, cookie=cookie, csrf="wrong")[0], 403)
        self.assertEqual(self.request("POST", "/api/run", body={}, cookie=cookie, csrf=data["csrf"])[0], 200)

    def test_body_limit_json_and_content_type(self):
        data, cookie = self.session()
        options = dict(cookie=cookie, csrf=data["csrf"])
        for body, expected in ((b"x" * (BODY_LIMIT + 1), 413), (b"{", 400), (b"[]", 400),
                               (b'{"max_steps":NaN}', 400), (b"\xff", 400)):
            with self.subTest(expected=expected, size=len(body)):
                self.assertEqual(self.request("POST", "/api/task", body=body, **options)[0], expected)
        self.assertEqual(self.request("POST", "/api/run", body="{}", headers={"Content-Type": "text/plain"}, **options)[0], 415)

    def test_step_run_reset_and_public_trace(self):
        data, cookie = self.session()
        options = dict(cookie=cookie, csrf=data["csrf"])
        code, state, _ = self.request("POST", "/api/step", body={}, **options)
        self.assertEqual((code, state["steps"], state["status"]), (200, 1, "running"))
        code, state, _ = self.request("POST", "/api/run", body={}, **options)
        self.assertEqual((code, state["status"]), (200, "success"))
        trace_id = state["trace_id"]
        code, trace, _ = self.request("GET", "/api/trace?trace_id=" + trace_id, cookie=cookie)
        self.assertEqual(code, 200)
        self.assertTrue(trace["events"][-1]["gate"]["allowed"])
        code, state, _ = self.request("POST", "/api/reset", body={}, **options)
        self.assertEqual((code, state["steps"], state["status"]), (200, 0, "ready"))
        self.assertNotEqual(trace_id, state["trace_id"])
        self.assertEqual(self.request("GET", "/api/trace?trace_id=" + trace_id, cookie=cookie)[0], 404)

    def test_cross_session_task_and_trace_ids_cannot_read_or_mutate(self):
        a, cookie_a = self.session()
        b, cookie_b = self.session()
        self.assertNotEqual(a["state"]["task_id"], b["state"]["task_id"])
        foreign_trace = a["state"]["trace_id"]
        self.assertEqual(self.request("GET", "/api/trace?trace_id=" + foreign_trace, cookie=cookie_b)[0], 404)
        self.assertEqual(self.request("GET", "/api/state?task_id=" + a["state"]["task_id"], cookie=cookie_b)[0], 400)
        self.assertEqual(self.request("POST", "/api/run", body={"task_id": a["state"]["task_id"]}, cookie=cookie_b, csrf=b["csrf"])[0], 400)
        self.assertEqual(self.request("POST", "/api/run", body={}, cookie=cookie_a, csrf=b["csrf"])[0], 403)
        code, state, _ = self.request("GET", "/api/state", cookie=cookie_a)
        self.assertEqual((code, state["steps"]), (200, 0))

    def test_sessions_do_not_share_scenarios_or_task_state(self):
        a, cookie_a = self.session()
        b, cookie_b = self.session()
        code, state, _ = self.request("POST", "/api/task", body={"scenario": "budget"}, cookie=cookie_a, csrf=a["csrf"])
        self.assertEqual((code, state["scenario"]), (200, "budget"))
        _, state, _ = self.request("POST", "/api/run", body={}, cookie=cookie_a, csrf=a["csrf"])
        self.assertEqual(state["status"], "blocked")
        _, state, _ = self.request("GET", "/api/state", cookie=cookie_b)
        self.assertEqual((state["status"], state["scenario"], state["steps"]), ("ready", "success", 0))

    def test_concurrent_repeated_run_executes_one_fixture_purchase(self):
        data, cookie = self.session()
        def run(_):
            return self.request("POST", "/api/run", body={}, cookie=cookie, csrf=data["csrf"])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, range(4)))
        for code, state, _ in results:
            self.assertEqual((code, state["status"], state["steps"]), (200, "success", 4))
        sid = cookie.split("=", 1)[1]
        self.assertEqual(self.server.sessions[sid].task.adapter.buy_calls, 1)

    def test_task_api_rejects_unapproved_fields_and_bad_limits(self):
        data, cookie = self.session()
        for body in ({"url": "https://example.com"}, {"max_steps": 0}, {"max_steps": True},
                     {"query": "x" * 1001}, {"scenario": "real_shop"}, {"trace_id": "other"}):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/task", body=body, cookie=cookie, csrf=data["csrf"])[0], 400)


if __name__ == "__main__":
    unittest.main()
