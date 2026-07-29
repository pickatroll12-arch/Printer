"""Interfaz de linea de comandos: demonio y cliente en el mismo binario."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config, ConfigError, load_config
from .escl import ESCLError, http_request
from .logging_setup import setup_logging
from .models import JobState, ValidationError
from .service import ScanService
from .unix_socket import send_command

POLL_INTERVAL = 2.0


# --------------------------------------------------------------------- systemd

def sd_notify(message: str) -> None:
    """Avisa a systemd (Type=notify). Silencioso si no hay NOTIFY_SOCKET."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):  # espacio de nombres abstracto
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(message.encode("utf-8"))
    except OSError:
        pass


# ---------------------------------------------------------------------- daemon

def cmd_serve(args: argparse.Namespace, config: Config) -> int:
    from .http_api import serve_in_thread as serve_http
    from .unix_socket import serve_in_thread as serve_unix

    logger = setup_logging(config.logging)
    logger.info("scanqueue %s arrancando (backend=%s, salida=%s)", __version__,
                config.scan.backend, config.output.dir)
    if config.source_path:
        logger.info("configuracion cargada de %s", config.source_path)

    service = ScanService(config)
    service.start()

    servers: list[Any] = []
    if config.service.port is not None:
        http_server, _ = serve_http(service)
        servers.append(http_server)
    if config.service.unix_socket:
        unix_server, _ = serve_unix(service, config.service.unix_socket,
                                    config.service.socket_mode)
        servers.append(unix_server)

    if not servers:
        logger.error("no hay ninguna interfaz activa; revisa [service]")
        service.stop()
        return 2

    stopping = threading.Event()

    def shutdown(signum: int, _frame: Any) -> None:
        if stopping.is_set():
            return
        stopping.set()
        logger.info("señal %s recibida; cerrando ordenadamente", signal.Signals(signum).name)
        sd_notify("STOPPING=1")
        for server in servers:
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    sd_notify("READY=1")
    report = service.health.check()
    logger.info("estado inicial de airsaned: %s", report.detail)

    try:
        while not stopping.wait(1.0):
            pass
    finally:
        for server in servers:
            try:
                server.server_close()
            except OSError:
                pass
        if config.service.unix_socket:
            try:
                Path(config.service.unix_socket).unlink(missing_ok=True)
            except OSError:
                pass
        service.stop()
        logger.info("scanqueue detenido")
    return 0


# ---------------------------------------------------------------------- cliente

class Client:
    """Habla con un scanqueue en marcha por socket UNIX o por HTTP."""

    def __init__(self, config: Config, prefer: str = "auto", timeout: float = 30.0) -> None:
        self.config = config
        self.timeout = timeout
        socket_path = config.service.unix_socket
        use_socket = bool(socket_path and socket_path.exists())
        if prefer == "unix":
            use_socket = True
        elif prefer == "http":
            use_socket = False
        self.use_socket = use_socket
        self.socket_path = socket_path
        host = config.service.host
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        self.base_url = f"http://{host}:{config.service.port}"

    def _http(self, method: str, path: str, payload: dict[str, Any] | None = None,
              query: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in query.items() if v not in (None, "")})
        headers = {"Content-Type": "application/json"}
        if self.config.service.auth_token:
            headers["Authorization"] = f"Bearer {self.config.service.auth_token}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        response = http_request(url, method=method, data=body, headers=headers,
                                timeout=self.timeout)
        try:
            data = json.loads(response.body.decode("utf-8")) if response.body else {}
        except json.JSONDecodeError:
            raise RuntimeError(
                f"respuesta no JSON del servicio (HTTP {response.status})") from None
        if response.status >= 400 and "error" in data:
            raise RuntimeError(data["error"])
        return data

    def _unix(self, request: dict[str, Any]) -> dict[str, Any]:
        assert self.socket_path is not None
        response = send_command(self.socket_path, request, timeout=self.timeout)
        if not response.get("ok", False):
            raise RuntimeError(response.get("error", "error desconocido"))
        return response

    def submit(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.use_socket:
            return self._unix({"command": "scan", "params": params})["job"]
        return self._http("POST", "/jobs", payload=params)

    def status(self, job_id: str) -> dict[str, Any]:
        if self.use_socket:
            return self._unix({"command": "status", "job_id": job_id})["job"]
        return self._http("GET", f"/jobs/{job_id}")

    def cancel(self, job_id: str) -> dict[str, Any]:
        if self.use_socket:
            return self._unix({"command": "cancel", "job_id": job_id})["job"]
        return self._http("DELETE", f"/jobs/{job_id}")

    def list(self, state: str = "", limit: int = 20) -> dict[str, Any]:
        if self.use_socket:
            return self._unix({"command": "list", "state": state, "limit": limit})
        return self._http("GET", "/jobs", query={"state": state, "limit": limit})

    def health(self) -> dict[str, Any]:
        if self.use_socket:
            return self._unix({"command": "health"})["health"]
        return self._http("GET", "/health")

    def capabilities(self) -> dict[str, Any]:
        if self.use_socket:
            return self._unix({"command": "capabilities"})["capabilities"]
        return self._http("GET", "/capabilities")


def _print(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print(_humanize(data))


def _humanize(data: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(data, dict):
        lines = []
        for key, value in data.items():
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}{key}:")
                lines.append(_humanize(value, indent + 1))
            else:
                lines.append(f"{pad}{key}: {value}")
        return "\n".join(lines)
    if isinstance(data, list):
        return "\n".join(_humanize(item, indent) for item in data) if data else f"{pad}(vacio)"
    return f"{pad}{data}"


def cmd_scan(args: argparse.Namespace, config: Config) -> int:
    client = Client(config, prefer=args.transport)
    params = {"dpi": args.dpi, "format": args.format, "mode": args.mode,
              "source": args.source, "page": args.page, "name": args.name}
    params = {k: v for k, v in params.items() if v is not None}
    job = client.submit(params)
    if not args.wait:
        _print(job, args.json)
        return 0

    job_id = job["id"]
    deadline = time.time() + args.wait_timeout
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        job = client.status(job_id)
        state = JobState(job["state"])
        if state.terminal:
            _print(job, args.json)
            if state is JobState.DONE:
                if not args.json:
                    print(f"\nListo: {job.get('output_path')}")
                return 0
            return 1
        if not args.json:
            print(f"[{job['state']}] intento {job.get('attempts', 0)}...",
                  file=sys.stderr)
    print("tiempo de espera agotado; el trabajo sigue en la cola", file=sys.stderr)
    return 2


def cmd_status(args: argparse.Namespace, config: Config) -> int:
    _print(Client(config, prefer=args.transport).status(args.job_id), args.json)
    return 0


def cmd_cancel(args: argparse.Namespace, config: Config) -> int:
    _print(Client(config, prefer=args.transport).cancel(args.job_id), args.json)
    return 0


def cmd_list(args: argparse.Namespace, config: Config) -> int:
    data = Client(config, prefer=args.transport).list(state=args.state, limit=args.limit)
    if args.json:
        _print(data, True)
        return 0
    jobs = data.get("jobs", [])
    if not jobs:
        print("(sin trabajos)")
        return 0
    print(f"{'ID':<14}{'ESTADO':<18}{'PPP':<6}{'FORMATO':<9}{'SALIDA'}")
    for job in jobs:
        print(f"{job['id']:<14}{job['state']:<18}{job['dpi']:<6}{job['format']:<9}"
              f"{job.get('output_path') or job.get('error') or ''}")
    return 0


def cmd_health(args: argparse.Namespace, config: Config) -> int:
    try:
        report = Client(config, prefer=args.transport).health()
    except (RuntimeError, ESCLError, OSError) as exc:
        # Sin servicio en marcha, al menos comprobamos airsaned directamente.
        print(f"scanqueue no responde: {exc}", file=sys.stderr)
        service_health = _standalone_health(config)
        _print(service_health, args.json)
        return 1
    _print(report, args.json)
    return 0 if report.get("airsane", {}).get("healthy") else 1


def _standalone_health(config: Config) -> dict[str, Any]:
    from .escl import ESCLClient
    from .health import HealthMonitor

    client = ESCLClient(config.airsane.base_url, scanner=config.airsane.scanner,
                        timeout=config.airsane.health_timeout)
    return {"airsane": HealthMonitor(config.airsane, client).check().to_dict()}


def cmd_capabilities(args: argparse.Namespace, config: Config) -> int:
    try:
        data = Client(config, prefer=args.transport).capabilities()
    except (RuntimeError, OSError):
        from .escl import ESCLClient

        client = ESCLClient(config.airsane.base_url, scanner=config.airsane.scanner,
                            timeout=config.airsane.health_timeout)
        try:
            data = {"available": True, **client.capabilities(force=True).to_dict()}
        except ESCLError as exc:
            data = {"available": False, "error": str(exc)}
    _print(data, args.json)
    return 0 if data.get("available", True) else 1


def cmd_config(args: argparse.Namespace, config: Config) -> int:
    _print(config.describe(), args.json)
    return 0


# ------------------------------------------------------------------ argumentos

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scanqueue",
        description="Cola de escaneo para una Canon G2010 servida por AirSane.")
    parser.add_argument("--version", action="version", version=f"scanqueue {__version__}")
    parser.add_argument("-c", "--config", help="ruta del fichero INI de configuracion")
    parser.add_argument("--json", action="store_true", help="salida en JSON")
    parser.add_argument("--transport", choices=("auto", "unix", "http"), default="auto",
                        help="como hablar con el servicio (por defecto: auto)")

    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="arranca el servicio (demonio)")
    serve.set_defaults(func=cmd_serve)

    scan = sub.add_parser("scan", help="encola un escaneo")
    scan.add_argument("--dpi", type=int, help="resolucion en puntos por pulgada")
    scan.add_argument("--format", help="pdf, jpeg, png o tiff")
    scan.add_argument("--mode", help="color, gray o lineart")
    scan.add_argument("--source", help="platen (cristal) o adf")
    scan.add_argument("--page", help="max, a4, letter, legal, a5 o a6")
    scan.add_argument("--name", help="nombre base del fichero resultante")
    scan.add_argument("-w", "--wait", action="store_true",
                      help="espera a que termine y muestra la ruta")
    scan.add_argument("--wait-timeout", type=float, default=600.0,
                      help="segundos maximos de espera con --wait")
    scan.set_defaults(func=cmd_scan)

    status = sub.add_parser("status", help="estado de un trabajo")
    status.add_argument("job_id")
    status.set_defaults(func=cmd_status)

    cancel = sub.add_parser("cancel", help="cancela un trabajo")
    cancel.add_argument("job_id")
    cancel.set_defaults(func=cmd_cancel)

    listing = sub.add_parser("list", help="lista los trabajos")
    listing.add_argument("--state", default="", help="filtra por estado")
    listing.add_argument("--limit", type=int, default=20)
    listing.set_defaults(func=cmd_list)

    health = sub.add_parser("health", help="comprueba scanqueue y airsaned")
    health.set_defaults(func=cmd_health)

    caps = sub.add_parser("capabilities", help="capacidades del escaner")
    caps.set_defaults(func=cmd_capabilities)

    conf = sub.add_parser("config", help="muestra la configuracion efectiva")
    conf.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error de configuracion: {exc}", file=sys.stderr)
        return 2
    try:
        return int(args.func(args, config))
    except ValidationError as exc:
        print(f"parametros invalidos: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, OSError, ESCLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
