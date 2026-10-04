"""Loopback-only local console. The cloud Site remains a read-only result board."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from .control import BusyError, ControlService, public_run

ASSETS = Path(__file__).resolve().parent / "console_assets"
MAX_REQUEST = 128 * 1024


def make_server(port: int = 8765, *, service: ControlService | None = None) -> ThreadingHTTPServer:
    control = service or ControlService()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

        def local_host(self) -> bool:
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def reply(self, code: int, payload: Any, *, content_type: str = "application/json; charset=utf-8") -> None:
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if not self.local_host():
                self.reply(403, {"success": False, "error": "local_access_required"})
                return
            path = urlsplit(self.path).path
            try:
                if path == "/":
                    self.reply(200, (ASSETS / "index.html").read_bytes(), content_type="text/html; charset=utf-8")
                elif path in {"/console.js", "/console.css"}:
                    name = path[1:]
                    self.reply(200, (ASSETS / name).read_bytes(), content_type="text/javascript; charset=utf-8" if name.endswith(".js") else "text/css; charset=utf-8")
                elif path == "/api/health":
                    self.reply(200, {"success": True, "service": "lab-model-monitor-console"})
                elif path == "/api/state":
                    self.reply(200, control.snapshot())
                elif path.startswith("/api/runs/"):
                    identity = str(UUID(path.removeprefix("/api/runs/")))
                    self.reply(200, {"success": True, "run": public_run(control.store.get(identity), detailed=True)})
                else:
                    self.reply(404, {"success": False, "error": "not_found"})
            except (KeyError, ValueError):
                self.reply(400, {"success": False, "error": "invalid_request_or_configuration"})
            except Exception:
                self.reply(500, {"success": False, "error": "local_operation_failed"})

        def do_POST(self) -> None:
            origin = self.headers.get("Origin")
            if (not self.local_host() or origin != "http://" + self.headers.get("Host", "")
                    or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json"):
                self.reply(403, {"success": False, "error": "same_origin_json_required"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_REQUEST:
                    self.reply(413, {"success": False, "error": "invalid_body_size"})
                    return
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object.")
                if self.path == "/api/settings":
                    self.reply(200, control.save(payload))
                elif self.path == "/api/actions":
                    self.reply(202, {"success": True, "job": control.start(payload.get("action", ""))})
                else:
                    self.reply(404, {"success": False, "error": "not_found"})
            except BusyError:
                self.reply(409, {"success": False, "error": "operation_running"})
            except (KeyError, ValueError, TypeError):
                self.reply(400, {"success": False, "error": "invalid_settings_or_credentials"})
            except Exception:
                self.reply(500, {"success": False, "error": "save_or_operation_failed"})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(*, port: int = 8765) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("Console port must be between 1024 and 65535.")
    with make_server(port) as server:
        print(f"Local console: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
