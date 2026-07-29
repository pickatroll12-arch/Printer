"""Carga de configuracion (INI) con valores por defecto y sobreescritura por entorno.

Orden de precedencia (de menor a mayor):
    1. valores por defecto de este modulo
    2. fichero INI (--config, $SCANQUEUE_CONFIG, o rutas estandar)
    3. variables de entorno SCANQUEUE_<SECCION>_<CLAVE>
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Iterable

DEFAULTS: dict[str, dict[str, str]] = {
    "service": {
        "host": "127.0.0.1",
        "port": "8099",
        "unix_socket": "",
        "socket_mode": "0660",
        "auth_token": "",
        "max_queue": "50",
        "state_dir": "~/.local/share/scanqueue",
        "history_days": "30",
    },
    "airsane": {
        "base_url": "http://127.0.0.1:8090",
        "scanner": "",
        "health_timeout": "5",
        "health_wait": "180",
        "health_poll": "3",
        "systemd_unit": "airsaned.service",
    },
    "scan": {
        "backend": "escl",
        "default_dpi": "300",
        "default_format": "pdf",
        "default_mode": "color",
        "default_source": "Platen",
        "default_page": "",
        "job_timeout": "240",
        "max_attempts": "3",
        "backoff_base": "4",
        "backoff_factor": "2",
        "backoff_max": "60",
        "scanimage_device": "",
        "post_command": "",
    },
    "output": {
        "dir": "~/Nextcloud/Escaneos",
        "filename_template": "scan_{date}_{time}_{job_id}.{ext}",
        "file_mode": "0644",
    },
    "logging": {
        "file": "~/.local/share/scanqueue/scanqueue.log",
        "audit_file": "~/.local/share/scanqueue/audit.jsonl",
        "level": "INFO",
        "max_bytes": "5242880",
        "backups": "5",
        "console": "true",
    },
}

CONFIG_SEARCH_PATH: tuple[str, ...] = (
    "~/.config/scanqueue/scanqueue.ini",
    "/etc/scanqueue/scanqueue.ini",
)

_TRUE = {"1", "true", "yes", "on", "si", "sí"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    """Configuracion invalida."""


def _as_bool(value: str, key: str) -> bool:
    low = value.strip().lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    raise ConfigError(f"{key}: valor booleano invalido: {value!r}")


def _as_int(value: str, key: str, minimum: int | None = None) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key}: se esperaba un entero, no {value!r}") from exc
    if minimum is not None and parsed < minimum:
        raise ConfigError(f"{key}: debe ser >= {minimum} (recibido {parsed})")
    return parsed


def _as_float(value: str, key: str, minimum: float | None = None) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key}: se esperaba un numero, no {value!r}") from exc
    if minimum is not None and parsed < minimum:
        raise ConfigError(f"{key}: debe ser >= {minimum} (recibido {parsed})")
    return parsed


def _expand(value: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(value.strip()))).resolve()


@dataclass(frozen=True)
class ServiceConfig:
    host: str
    port: int | None  # None = API HTTP desactivada; 0 = puerto efimero
    unix_socket: Path | None
    socket_mode: int
    auth_token: str
    max_queue: int
    state_dir: Path
    history_days: int


@dataclass(frozen=True)
class AirSaneConfig:
    base_url: str
    scanner: str
    health_timeout: float
    health_wait: float
    health_poll: float
    systemd_unit: str


@dataclass(frozen=True)
class ScanConfig:
    backend: str
    default_dpi: int
    default_format: str
    default_mode: str
    default_source: str
    default_page: str
    job_timeout: float
    max_attempts: int
    backoff_base: float
    backoff_factor: float
    backoff_max: float
    scanimage_device: str
    post_command: str


@dataclass(frozen=True)
class OutputConfig:
    dir: Path
    filename_template: str
    file_mode: int


@dataclass(frozen=True)
class LoggingConfig:
    file: Path
    audit_file: Path
    level: str
    max_bytes: int
    backups: int
    console: bool


@dataclass(frozen=True)
class Config:
    service: ServiceConfig
    airsane: AirSaneConfig
    scan: ScanConfig
    output: OutputConfig
    logging: LoggingConfig
    source_path: Path | None = field(default=None)

    def describe(self) -> dict[str, Any]:
        """Vuelca la configuracion como dict serializable, ocultando secretos."""
        out: dict[str, Any] = {"config_file": str(self.source_path or "")}
        for section in fields(self):
            if section.name == "source_path":
                continue
            value = getattr(self, section.name)
            out[section.name] = {
                f.name: ("***" if f.name == "auth_token" and getattr(value, f.name) else str(getattr(value, f.name)))
                for f in fields(value)
            }
        return out


def _merge_env(raw: dict[str, dict[str, str]], environ: dict[str, str]) -> None:
    """Aplica SCANQUEUE_<SECCION>_<CLAVE> sobre el mapa de valores."""
    for section, options in raw.items():
        for key in options:
            env_key = f"SCANQUEUE_{section.upper()}_{key.upper()}"
            if env_key in environ:
                options[key] = environ[env_key]


def _read_raw(path: Path | None) -> dict[str, dict[str, str]]:
    raw = {section: dict(options) for section, options in DEFAULTS.items()}
    if path is None:
        return raw
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except OSError as exc:
        raise ConfigError(f"no se pudo leer {path}: {exc}") from exc
    except configparser.Error as exc:
        raise ConfigError(f"INI invalido en {path}: {exc}") from exc

    for section in parser.sections():
        if section not in raw:
            raise ConfigError(f"{path}: seccion desconocida [{section}]")
        for key, value in parser.items(section):
            if key not in raw[section]:
                raise ConfigError(f"{path}: clave desconocida {key!r} en [{section}]")
            raw[section][key] = value
    return raw


def find_config_file(explicit: str | os.PathLike[str] | None = None,
                     environ: dict[str, str] | None = None,
                     search_path: Iterable[str] = CONFIG_SEARCH_PATH) -> Path | None:
    environ = os.environ if environ is None else environ
    if explicit:
        path = Path(os.path.expanduser(str(explicit)))
        if not path.is_file():
            raise ConfigError(f"fichero de configuracion no encontrado: {path}")
        return path
    env_path = environ.get("SCANQUEUE_CONFIG")
    if env_path:
        path = Path(os.path.expanduser(env_path))
        if not path.is_file():
            raise ConfigError(f"SCANQUEUE_CONFIG apunta a un fichero inexistente: {path}")
        return path
    for candidate in search_path:
        path = Path(os.path.expanduser(candidate))
        if path.is_file():
            return path
    return None


def load_config(explicit: str | os.PathLike[str] | None = None,
                environ: dict[str, str] | None = None) -> Config:
    environ = dict(os.environ) if environ is None else dict(environ)
    path = find_config_file(explicit, environ)
    raw = _read_raw(path)
    _merge_env(raw, environ)

    svc, air, scan, out, log = (raw["service"], raw["airsane"], raw["scan"],
                                raw["output"], raw["logging"])

    backend = scan["backend"].strip().lower()
    if backend not in {"escl", "scanimage"}:
        raise ConfigError(f"scan.backend: valor invalido {backend!r} (escl|scanimage)")

    base_url = air["base_url"].strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"airsane.base_url: debe empezar por http:// o https:// ({base_url!r})")

    socket_path = svc["unix_socket"].strip()
    # Puerto vacio = API HTTP desactivada. Puerto 0 = el sistema elige uno libre.
    port_raw = svc["port"].strip()
    port = _as_int(port_raw, "service.port", 0) if port_raw else None
    if port is None and not socket_path:
        raise ConfigError("service: hay que habilitar al menos el puerto TCP o el socket UNIX")

    config = Config(
        service=ServiceConfig(
            host=svc["host"].strip() or "127.0.0.1",
            port=port,
            unix_socket=_expand(socket_path) if socket_path else None,
            socket_mode=int(svc["socket_mode"].strip() or "0660", 8),
            auth_token=svc["auth_token"].strip(),
            max_queue=_as_int(svc["max_queue"], "service.max_queue", 1),
            state_dir=_expand(svc["state_dir"]),
            history_days=_as_int(svc["history_days"], "service.history_days", 0),
        ),
        airsane=AirSaneConfig(
            base_url=base_url,
            scanner=air["scanner"].strip(),
            health_timeout=_as_float(air["health_timeout"], "airsane.health_timeout", 0.1),
            health_wait=_as_float(air["health_wait"], "airsane.health_wait", 0),
            health_poll=_as_float(air["health_poll"], "airsane.health_poll", 0.1),
            systemd_unit=air["systemd_unit"].strip(),
        ),
        scan=ScanConfig(
            backend=backend,
            default_dpi=_as_int(scan["default_dpi"], "scan.default_dpi", 50),
            default_format=scan["default_format"].strip().lower(),
            default_mode=scan["default_mode"].strip().lower(),
            default_source=scan["default_source"].strip() or "Platen",
            default_page=scan["default_page"].strip().lower(),
            job_timeout=_as_float(scan["job_timeout"], "scan.job_timeout", 5),
            max_attempts=_as_int(scan["max_attempts"], "scan.max_attempts", 1),
            backoff_base=_as_float(scan["backoff_base"], "scan.backoff_base", 0),
            backoff_factor=_as_float(scan["backoff_factor"], "scan.backoff_factor", 1),
            backoff_max=_as_float(scan["backoff_max"], "scan.backoff_max", 0),
            scanimage_device=scan["scanimage_device"].strip(),
            post_command=scan["post_command"].strip(),
        ),
        output=OutputConfig(
            dir=_expand(out["dir"]),
            filename_template=out["filename_template"].strip(),
            file_mode=int(out["file_mode"].strip() or "0644", 8),
        ),
        logging=LoggingConfig(
            file=_expand(log["file"]),
            audit_file=_expand(log["audit_file"]),
            level=log["level"].strip().upper(),
            max_bytes=_as_int(log["max_bytes"], "logging.max_bytes", 0),
            backups=_as_int(log["backups"], "logging.backups", 0),
            console=_as_bool(log["console"], "logging.console"),
        ),
        source_path=path,
    )

    # Los valores por defecto de escaneo se validan aqui para fallar al arrancar,
    # no en mitad de un trabajo con el papel ya en el cristal.
    from .models import (normalize_format, normalize_mode,  # import tardio: evita ciclo
                         normalize_page, normalize_source)

    for key, validate, value in (
        ("scan.default_format", normalize_format, config.scan.default_format),
        ("scan.default_mode", normalize_mode, config.scan.default_mode),
        ("scan.default_source", normalize_source, config.scan.default_source),
        ("scan.default_page", normalize_page, config.scan.default_page),
    ):
        try:
            validate(value)
        except ValueError as exc:
            raise ConfigError(f"{key}: {exc}") from exc
    return config
