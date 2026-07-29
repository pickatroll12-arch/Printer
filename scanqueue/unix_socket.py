"""Socket UNIX con protocolo JSON por lineas.

Pensado para scripts, botones del panel de XFCE o un atajo de teclado: no hay
que hablar HTTP ni depender de curl.

    printf '{"command":"scan","dpi":300,"format":"pdf"}\\n' | nc -U /ruta/scanqueue.sock

Cada peticion es una linea JSON y la respuesta es otra linea JSON.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import socketserver
import threading
from pathlib import Path
from typing import Any

from .models import ValidationError
from .service import NotFound, ScanService
from .worker import QueueFull

LOG = logging.getLogger("scanqueue.socket")

MAX_LINE = 64 * 1024
DEFAULT_SOCKET_MODE = 0o660


def handle_command(service: ScanService, request: dict[str, Any],
                   client: str = "unix") -> dict[str, Any]:
    """Ejecuta un comando del protocolo y devuelve la respuesta serializable."""
    command = str(request.get("command") or request.get("cmd") or "").strip().lower()
    if not command:
        raise ValidationError("falta el campo 'command'")

    if command == "ping":
        return {"ok": True, "pong": True}
    if command in ("scan", "submit", "enqueue"):
        params = request.get("params") if isinstance(request.get("params"), dict) else request
        job = service.submit(params, client=client)
        return {"ok": True, "job": service.job_view(job)}
    if command in ("status", "job", "get"):
        job_id = str(request.get("job_id") or request.get("id") or "")
        if not job_id:
            raise ValidationError("falta 'job_id'")
        return {"ok": True, "job": service.job_view(service.get(job_id))}
    if command in ("list", "jobs"):
        jobs = service.list(state=str(request.get("state") or ""),
                            limit=int(request.get("limit") or 50),
                            offset=int(request.get("offset") or 0))
        return {"ok": True, "jobs": [service.job_view(job) for job in jobs],
                "queue": service.worker.stats()}
    if command == "cancel":
        job_id = str(request.get("job_id") or request.get("id") or "")
        if not job_id:
            raise ValidationError("falta 'job_id'")
        return {"ok": True, "job": service.job_view(service.cancel(job_id))}
    if command == "health":
        return {"ok": True, "health": service.health_view()}
    if command in ("capabilities", "caps"):
        return {"ok": True, "capabilities": service.capabilities_view()}
    if command == "info":
        return {"ok": True, "info": service.info_view()}
    if command in ("stats", "queue"):
        return {"ok": True, "queue": service.worker.stats()}

    raise ValidationError(f"comando desconocido: {command}")


class _RequestHandler(socketserver.StreamRequestHandler):
    timeout = 30
    service: ScanService  # inyectado

    def handle(self) -> None:
        try:
            for raw in self.rfile:
                if len(raw) > MAX_LINE:
                    self._reply({"ok": False, "error": "peticion demasiado larga"})
                    return
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                self._reply(self._process(line))
        except (socket.timeout, TimeoutError):
            LOG.debug("cliente del socket UNIX inactivo; se cierra")
        except (BrokenPipeError, ConnectionResetError):
            LOG.debug("el cliente del socket cerro la conexion")

    def _process(self, line: str) -> dict[str, Any]:
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"JSON invalido: {exc}"}
        if not isinstance(request, dict):
            return {"ok": False, "error": "se esperaba un objeto JSON"}
        try:
            return handle_command(self.service, request)
        except ValidationError as exc:
            return {"ok": False, "error": str(exc), "kind": "validation"}
        except NotFound as exc:
            return {"ok": False, "error": str(exc), "kind": "not_found"}
        except QueueFull as exc:
            return {"ok": False, "error": str(exc), "kind": "queue_full"}
        except Exception as exc:  # pragma: no cover - red de seguridad
            LOG.exception("error atendiendo el comando del socket")
            return {"ok": False, "error": f"error interno: {exc}"}

    def _reply(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.wfile.write(data + b"\n")
        self.wfile.flush()


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    request_queue_size = 8


def create_unix_server(service: ScanService, path: Path,
                       mode: int = DEFAULT_SOCKET_MODE) -> _UnixServer:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        # Un socket huerfano de una ejecucion anterior impide el bind.
        if path.is_socket():
            path.unlink()
        else:
            raise OSError(f"{path} existe y no es un socket")
    handler = type("ScanQueueUnixHandler", (_RequestHandler,), {"service": service})
    server = _UnixServer(str(path), handler)
    os.chmod(path, mode)
    LOG.info("socket UNIX escuchando en %s", path)
    return server


def serve_in_thread(service: ScanService, path: Path,
                    mode: int = DEFAULT_SOCKET_MODE) -> tuple[_UnixServer, threading.Thread]:
    server = create_unix_server(service, path, mode)
    thread = threading.Thread(target=server.serve_forever, args=(0.5,),
                              name="scanqueue-unix", daemon=True)
    thread.start()
    return server, thread


def send_command(path: Path, request: dict[str, Any], timeout: float = 30.0
                 ) -> dict[str, Any]:
    """Cliente minimo del socket, usado por la CLI."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(path))
        sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
        chunks: list[bytes] = []
        while b"\n" not in b"".join(chunks):
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    payload = b"".join(chunks).split(b"\n", 1)[0]
    if not payload:
        raise ConnectionError("el servicio cerro la conexion sin responder")
    return json.loads(payload.decode("utf-8"))
