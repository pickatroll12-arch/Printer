"""API HTTP JSON sobre http.server (sin Flask).

En un Core 2 Duo con 3 GB, un servidor de la biblioteca estandar consume una
fraccion de la memoria de un stack Flask+WSGI y no arrastra dependencias al
AppImage. La forma de la API es la misma que tendria con Flask.

    GET    /health              estado del servicio y de airsaned
    GET    /info                version y configuracion efectiva
    GET    /capabilities        capacidades del escaner (ppp, formatos)
    GET    /jobs                lista de trabajos (?state=&limit=&offset=)
    POST   /jobs                encola un trabajo (JSON o form-urlencoded)
    GET    /jobs/<id>           estado de un trabajo
    DELETE /jobs/<id>           cancela un trabajo
    GET    /jobs/<id>/file      descarga el resultado
"""

from __future__ import annotations

import hmac
import json
import logging
import socket
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .models import ValidationError, mime_for
from .service import NotFound, ScanService
from .worker import QueueFull

LOG = logging.getLogger("scanqueue.http")

MAX_BODY = 64 * 1024


class _Handler(BaseHTTPRequestHandler):
    server_version = "scanqueue"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    service: ScanService  # inyectado por el servidor

    # ------------------------------------------------------------- utilidades

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        LOG.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, payload: bytes, content_type: str,
              extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _json(self, status: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str, **extra: Any) -> None:
        self._json(status, {"error": message, "status": status, **extra})

    def _read_params(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            raise ValidationError(f"cuerpo demasiado grande (max {MAX_BODY} bytes)")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        text = raw.decode("utf-8", "replace")
        if content_type == "application/x-www-form-urlencoded":
            return {k: v[-1] for k, v in urllib.parse.parse_qs(text).items()}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"JSON invalido: {exc}") from exc
        if not isinstance(data, dict):
            raise ValidationError("se esperaba un objeto JSON")
        return data

    def _authorized(self, query: dict[str, list[str]]) -> bool:
        token = self.service.config.service.auth_token
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not supplied:
            supplied = (query.get("token") or [""])[-1]
        return hmac.compare_digest(supplied, token)

    # ------------------------------------------------------------------ rutas

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        parts = [segment for segment in parsed.path.strip("/").split("/") if segment]

        if not self._authorized(query):
            self._error(HTTPStatus.UNAUTHORIZED, "token invalido o ausente")
            return

        try:
            self._route(method, parts, query)
        except ValidationError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except NotFound as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except QueueFull as exc:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        except BrokenPipeError:  # pragma: no cover - cliente que se va
            LOG.debug("el cliente cerro la conexion")
        except Exception as exc:  # pragma: no cover - red de seguridad
            LOG.exception("error interno atendiendo %s %s", method, self.path)
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"error interno: {exc}")

    def _route(self, method: str, parts: list[str], query: dict[str, list[str]]) -> None:
        service = self.service

        if not parts:
            if method != "GET":
                self._error(HTTPStatus.METHOD_NOT_ALLOWED, "metodo no permitido")
                return
            self._json(HTTPStatus.OK, {
                "service": "scanqueue",
                "endpoints": ["GET /health", "GET /info", "GET /capabilities",
                              "GET /jobs", "POST /jobs", "GET /jobs/<id>",
                              "DELETE /jobs/<id>", "GET /jobs/<id>/file"],
            })
            return

        head = parts[0]

        if head == "health" and method == "GET":
            report = service.health_view()
            status = HTTPStatus.OK if report["airsane"]["healthy"] \
                else HTTPStatus.SERVICE_UNAVAILABLE
            self._json(status, report)
            return

        if head == "info" and method == "GET":
            self._json(HTTPStatus.OK, service.info_view())
            return

        if head == "capabilities" and method == "GET":
            self._json(HTTPStatus.OK, service.capabilities_view())
            return

        if head == "jobs":
            if len(parts) == 1:
                if method == "GET":
                    jobs = service.list(
                        state=(query.get("state") or [""])[-1],
                        limit=int((query.get("limit") or ["50"])[-1]),
                        offset=int((query.get("offset") or ["0"])[-1]))
                    self._json(HTTPStatus.OK, {
                        "jobs": [service.job_view(job) for job in jobs],
                        "queue": service.worker.stats(),
                    })
                    return
                if method == "POST":
                    job = service.submit(self._read_params(),
                                         client=f"http:{self.address_string()}")
                    self._json(HTTPStatus.ACCEPTED, service.job_view(job))
                    return
                self._error(HTTPStatus.METHOD_NOT_ALLOWED, "metodo no permitido")
                return

            job_id = parts[1]
            if len(parts) == 2:
                if method == "GET":
                    self._json(HTTPStatus.OK, service.job_view(service.get(job_id)))
                    return
                if method == "DELETE":
                    self._json(HTTPStatus.OK, service.job_view(service.cancel(job_id)))
                    return
                self._error(HTTPStatus.METHOD_NOT_ALLOWED, "metodo no permitido")
                return

            if len(parts) == 3 and parts[2] == "file" and method == "GET":
                path = service.result_path(job_id)
                job = service.get(job_id)
                data = path.read_bytes()
                self._send(HTTPStatus.OK, data, mime_for(job.format),
                           {"Content-Disposition":
                            f'attachment; filename="{path.name}"'})
                return

        self._error(HTTPStatus.NOT_FOUND, f"ruta desconocida: /{'/'.join(parts)}")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # Peticiones cortas y pocos clientes: no hace falta una cola grande.
    request_queue_size = 16


def create_http_server(service: ScanService) -> tuple[_Server, Callable[[], None]]:
    """Crea el servidor HTTP y devuelve (servidor, funcion para servir)."""
    cfg = service.config.service
    handler = type("ScanQueueHandler", (_Handler,), {"service": service})
    address_family = socket.AF_INET6 if ":" in cfg.host else socket.AF_INET
    server_class = type("ScanQueueServer", (_Server,),
                        {"address_family": address_family})
    server = server_class((cfg.host, cfg.port), handler)

    def serve() -> None:
        LOG.info("API HTTP escuchando en http://%s:%d", cfg.host, server.server_port)
        server.serve_forever(poll_interval=0.5)

    return server, serve


def serve_in_thread(service: ScanService) -> tuple[_Server, threading.Thread]:
    server, serve = create_http_server(service)
    thread = threading.Thread(target=serve, name="scanqueue-http", daemon=True)
    thread.start()
    return server, thread
