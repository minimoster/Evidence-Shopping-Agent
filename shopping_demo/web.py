"""Local-only standard-library WebUI, deliberately not a production service."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

from .core import DEFAULT_QUERY, SCENARIOS, Task

BODY_LIMIT = 8192
COOKIE_NAME = "offline_shopping_session"
STATIC = Path(__file__).with_name("static")


@dataclass
class Session:
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    task: Task = field(default_factory=Task)
    lock: threading.RLock = field(default_factory=threading.RLock)
    touched: float = field(default_factory=time.monotonic)


class DemoServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int]):
        if address[0] != "127.0.0.1":
            raise ValueError("This offline demo only binds to 127.0.0.1")
        self.sessions: dict[str, Session] = {}
        self.sessions_lock = threading.RLock()
        # Files are a fixed package allowlist; request paths are never filesystem paths.
        self.static_files = {
            "/": ("text/html; charset=utf-8", (STATIC / "index.html").read_bytes()),
            "/app.js": ("text/javascript; charset=utf-8", (STATIC / "app.js").read_bytes()),
            "/style.css": ("text/css; charset=utf-8", (STATIC / "style.css").read_bytes()),
        }
        super().__init__(address, Handler)
        self.allowed_host = f"127.0.0.1:{self.server_port}"
        self.allowed_origin = "http://" + self.allowed_host


class Handler(BaseHTTPRequestHandler):
    server: DemoServer
    protocol_version = "HTTP/1.0"
    server_version = "OfflineShoppingDemo"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format: str, *args: object) -> None:
        # Neither request contents, cookies nor queries are logged.
        pass

    def _send(self, code: int, payload: object, *, cookie: str | None = None,
              content_type: str = "application/json; charset=utf-8") -> None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'; object-src 'none'")
        if cookie:
            # HttpOnly and Strict, intentionally no Secure on a loopback HTTP demo.
            self.send_header("Set-Cookie", f"{COOKIE_NAME}={cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800")
        self.end_headers()
        self.wfile.write(data)

    def _reject(self, code: int, reason: str) -> None:
        self._send(code, {"error": reason})

    def _route(self) -> tuple[str, str] | None:
        if self.headers.get_all("Host") != [self.server.allowed_host]:
            self._reject(403, "host_not_allowed")
            return None
        origins = self.headers.get_all("Origin") or []
        if len(origins) > 1 or (origins and origins[0] != self.server.allowed_origin):
            self._reject(403, "origin_not_allowed")
            return None
        if self.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
            self._reject(403, "cross_site_request_not_allowed")
            return None
        try:
            parsed = urlsplit(self.path)
        except ValueError:
            self._reject(400, "invalid_path")
            return None
        decoded = unquote(parsed.path)
        if parsed.scheme or parsed.netloc or "\\" in decoded or "\x00" in decoded or any(part in {".", ".."} for part in decoded.split("/")) or "%" in decoded:
            self._reject(400, "invalid_path")
            return None
        return decoded, parsed.query

    def _session(self, *, create: bool = False) -> tuple[str, Session] | None:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
            sid = jar[COOKIE_NAME].value if COOKIE_NAME in jar else ""
        except Exception:
            sid = ""
        with self.server.sessions_lock:
            now = time.monotonic()
            for key in list(self.server.sessions):
                if now - self.server.sessions[key].touched > 28800:
                    del self.server.sessions[key]
            session = self.server.sessions.get(sid)
            if session is None and create:
                if len(self.server.sessions) >= 64:
                    self._reject(503, "local_session_capacity_reached")
                    return None
                sid, session = secrets.token_urlsafe(32), Session()
                self.server.sessions[sid] = session
            if session is None:
                self._reject(401, "session_required")
                return None
            session.touched = now
            return sid, session

    def do_GET(self) -> None:
        route = self._route()
        if route is None:
            return
        path, query = route
        if path in self.server.static_files and not query:
            mime, data = self.server.static_files[path]
            self._send(200, data, content_type=mime)
            return
        if path not in {"/api/session", "/api/state", "/api/trace"}:
            self._reject(404, "not_found")
            return
        if path != "/api/trace" and query:
            self._reject(400, "unexpected_query")
            return
        result = self._session(create=path == "/api/session")
        if result is None:
            return
        sid, session = result
        with session.lock:
            if path == "/api/session":
                self._send(200, {"csrf": session.csrf, "state": session.task.state(),
                                 "scenarios": SCENARIOS, "default_query": DEFAULT_QUERY}, cookie=sid)
            elif path == "/api/state":
                self._send(200, session.task.state())
            else:
                params = parse_qs(query, keep_blank_values=True)
                if set(params) != {"trace_id"} or params["trace_id"] != [session.task.trace_id]:
                    # Never search another session, even with a known task/trace ID.
                    self._reject(404, "trace_not_found_in_this_session")
                    return
                self._send(200, session.task.trace())

    def do_POST(self) -> None:
        route = self._route()
        if route is None:
            return
        path, query = route
        if query or path not in {"/api/task", "/api/step", "/api/run", "/api/reset"}:
            self._reject(404, "not_found")
            return
        result = self._session()
        if result is None:
            return
        _, session = result
        csrf = self.headers.get_all("X-CSRF-Token") or []
        if len(csrf) != 1 or not secrets.compare_digest(csrf[0], session.csrf):
            self._reject(403, "csrf_required")
            return
        lengths = self.headers.get_all("Content-Length") or []
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            self._reject(400, "fixed_content_length_required")
            return
        try:
            length = int(lengths[0])
        except ValueError:
            self._reject(400, "invalid_content_length")
            return
        if not 0 < length <= BODY_LIMIT:
            self._reject(413, "request_body_too_large_or_empty")
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold() != "application/json":
            self._reject(415, "application_json_required")
            return
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError()
            body = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError, RecursionError):
            self._reject(400, "invalid_json_body")
            return
        with session.lock:
            try:
                if path == "/api/task":
                    if set(body) - {"query", "scenario", "max_steps"}:
                        raise ValueError("unexpected_fields")
                    session.task = Task(body.get("query", DEFAULT_QUERY), body.get("scenario", "success"),
                                        max_steps=body.get("max_steps", 12))
                else:
                    if body:
                        raise ValueError("unexpected_fields")
                    if path == "/api/reset":
                        task = session.task
                        session.task = Task(task.query, task.scenario, max_steps=task.max_steps)
                    elif path == "/api/step":
                        session.task.step()
                    else:
                        session.task.run()
            except (ValueError, TypeError):
                self._reject(400, "invalid_task_request")
                return
            self._send(200, session.task.state())

    def do_OPTIONS(self) -> None:
        self._reject(405, "method_not_allowed")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="离线脚本演示 · 非 LLM · 不真实购物")
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be 0..65535")
    with DemoServer((args.host, args.port)) as server:
        print(f"离线脚本演示 · 非 LLM · 不真实购物\nOpen {server.allowed_origin}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
