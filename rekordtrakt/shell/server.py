"""Local web server for the app's windows: pages, a status API and a live event stream (server-sent events).

Standard library only. It listens on 127.0.0.1 alone, on a random port, and every request needs the per-run token
(in the URL for pages and the stream, in a header for actions), so other programs and web pages can't drive it.
"""
import json
import os
import queue
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from rekordtrakt.shell.events import to_json

WEB_DIR = Path(__file__).resolve().parent / "web"
PAGES = {"/app": "app.html", "/debug": "debug.html"}
KEEPALIVE = 10.0
BATCH = 500
MAX_BODY = 4 * 1024 * 1024     # an imported .midi.xml mapping file can be large
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'")
# The main window's code lives in files (web/app.css, web/js/*.js), so its page allows scripts from here only.
CSP_APP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; "
           "img-src 'self' data:; base-uri 'none'; form-action 'none'")
PAGE_CSP = {"/app": CSP_APP}
# Static files: the window's own code and styles, served without the token (they're the program's public source,
# nothing about this PC); a strict name pattern keeps anything else out.
STATIC = re.compile(r"^/web/((?:js/)?[a-z0-9][a-z0-9_-]*\.(js|css))$")
STATIC_TYPES = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}
FRAMING = {"/app": "; frame-src 'self'; frame-ancestors 'none'",     # the app window shows the debug page in a tab
           "/debug": "; frame-ancestors 'self'"}


class UiServer:
    """actions: name -> fn(body) returning a JSON-able result, for POST /api/<name> (body: the request's JSON object,
    or {}). status: fn() -> dict."""

    def __init__(self, hub, status, actions, port=0, on_stream_closed=None, gets=None):
        self.hub = hub
        self.status = status
        self.actions = actions
        self.gets = gets or {}              # extra read-only JSON endpoints: path -> fn()
        self.on_stream_closed = on_stream_closed or (lambda kinds: None)   # a window went away
        self.token = secrets.token_urlsafe(18)
        self.closing = threading.Event()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread = None

    def url(self, page="debug"):
        return f"http://127.0.0.1:{self.port}/{page}?token={self.token}"

    def start(self):
        self._thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.25},
                                        name="ui-server", daemon=True)
        self._thread.start()

    def stop(self):
        self.closing.set()
        self.httpd.shutdown()
        self.httpd.server_close()

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "RekordTrakt"

            def log_message(self, *_):
                pass

            # --- checks ---------------------------------------------------------------------------------
            def _host_ok(self):
                return self.headers.get("Host") in (f"127.0.0.1:{server.port}", f"localhost:{server.port}")

            def _token_ok(self, query):
                given = self.headers.get("X-RekordTrakt-Token") or (query.get("token") or [""])[0]
                return secrets.compare_digest(given, server.token)

            def _reply(self, code, body, ctype="application/json; charset=utf-8", csp=CSP):
                try:
                    self._write(code, body, ctype, csp)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    pass                    # the window went away before the answer: nothing to do

            def _write(self, code, body, ctype, csp):
                data = body if isinstance(body, bytes) else body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                if ctype.startswith("text/html"):
                    self.send_header("Content-Security-Policy", csp)
                self.end_headers()
                self.wfile.write(data)

            def _json(self, code, obj):
                self._reply(code, json.dumps(obj, default=str))

            # --- routes ---------------------------------------------------------------------------------
            def do_GET(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                static = STATIC.match(url.path)
                if static and self._host_ok():
                    path = WEB_DIR / static.group(1)
                    if path.is_file():
                        return self._reply(200, path.read_bytes(), STATIC_TYPES[static.group(2)])
                    return self._json(404, {"error": "not found"})
                if not self._host_ok() or not self._token_ok(query):
                    return self._json(403, {"error": "forbidden"})
                if url.path in PAGES:
                    return self._reply(200, (WEB_DIR / PAGES[url.path]).read_bytes(), "text/html; charset=utf-8",
                                       PAGE_CSP.get(url.path, CSP) + FRAMING.get(url.path, "; frame-ancestors 'none'"))
                if url.path == "/api/status":
                    return self._json(200, server.status())
                if url.path in server.gets:
                    return self._json(200, server.gets[url.path]())
                if url.path == "/events":
                    return self._stream()
                return self._json(404, {"error": "not found"})

            def do_POST(self):
                url = urlparse(self.path)
                origin = self.headers.get("Origin")
                if (not self._host_ok() or not self.headers.get("X-RekordTrakt-Token") or not self._token_ok({})
                        or (origin and origin not in (f"http://127.0.0.1:{server.port}", f"http://localhost:{server.port}"))):
                    return self._json(403, {"error": "forbidden"})
                name = url.path.removeprefix("/api/")
                action = server.actions.get(name)
                if not action:
                    return self._json(404, {"error": f"no action '{name}'"})
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > MAX_BODY:
                        return self._json(413, {"ok": False, "error": "request too large"})
                    body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                    if not isinstance(body, dict):
                        raise ValueError("expected a JSON object")
                except ValueError as e:
                    return self._json(400, {"ok": False, "error": f"bad request: {e}"})
                try:
                    return self._json(200, {"ok": True, "result": action(body)})
                except (ValueError, KeyError, RuntimeError) as e:
                    return self._json(400, {"ok": False, "error": str(e)})
                except Exception as e:
                    return self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

            def _stream(self):
                kinds = parse_qs(urlparse(self.path).query).get("kinds")
                wanted = set(kinds[0].split(",")) if kinds else None      # e.g. the main window: view,status
                q, backlog = server.hub.subscribe()
                if wanted:
                    backlog = [e for e in backlog if e["kind"] in wanted]
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self._send_events(backlog, "backlog")
                    while not server.closing.is_set():
                        try:
                            batch = [q.get(timeout=KEEPALIVE)]
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            continue
                        while len(batch) < BATCH:
                            try:
                                batch.append(q.get_nowait())
                            except queue.Empty:
                                break
                        if wanted:
                            batch = [e for e in batch if e["kind"] in wanted]
                            if not batch:
                                continue
                        self._send_events(batch)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    pass                    # the window was closed
                finally:
                    server.hub.unsubscribe(q)
                    try:
                        server.on_stream_closed(wanted)
                    except Exception:
                        pass

            def _send_events(self, events, name=None):
                head = f"event: {name}\n" if name else ""
                if name:                    # the backlog goes as one message, so the page can render it in one go
                    payload = head + "data: [" + ",".join(to_json(e) for e in events) + "]\n\n"
                else:
                    payload = "".join(f"data: {to_json(e)}\n\n" for e in events)
                self.wfile.write(payload.encode("utf-8"))
                self.wfile.flush()

        return Handler


def open_folder(path):
    os.startfile(str(path))
