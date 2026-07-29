"""Vigilancia de airsaned: comprobacion previa a cada trabajo y espera activa.

El reinicio automatico ya lo hace systemd. Aqui no reiniciamos nada: solo
detectamos la caida y esperamos activamente a que el servicio vuelva, para no
quemar intentos de escaneo contra un backend que sabemos que esta muerto.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import AirSaneConfig
from .escl import ESCLClient, ESCLError, http_request

LOG = logging.getLogger("scanqueue.health")


@dataclass
class HealthReport:
    healthy: bool
    detail: str
    checked_at: float = field(default_factory=time.time)
    http_status: int | None = None
    scanner_url: str | None = None
    scanner_state: str | None = None
    systemd_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "detail": self.detail,
            "checked_at": round(self.checked_at, 3),
            "http_status": self.http_status,
            "scanner_url": self.scanner_url,
            "scanner_state": self.scanner_state,
            "systemd_state": self.systemd_state,
        }


def systemd_state(unit: str, timeout: float = 3.0) -> str | None:
    """`systemctl is-active`, o None si systemctl no esta disponible."""
    if not unit or not shutil.which("systemctl"):
        return None
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.debug("systemctl is-active %s fallo: %s", unit, exc)
        return None
    return (result.stdout or result.stderr).strip() or None


class HealthMonitor:
    """Comprueba airsaned y espera su reinicio automatico cuando cae."""

    def __init__(self, cfg: AirSaneConfig, client: ESCLClient,
                 sleeper: Callable[[float], None] | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        self.cfg = cfg
        self.client = client
        self._sleep = sleeper or time.sleep
        self._clock = clock or time.monotonic
        self.last_report: HealthReport | None = None

    def check(self) -> HealthReport:
        """Una comprobacion puntual. Nunca lanza excepciones."""
        unit_state = systemd_state(self.cfg.systemd_unit)
        report = HealthReport(healthy=False, detail="sin comprobar",
                              systemd_state=unit_state)
        try:
            response = http_request(self.cfg.base_url + "/",
                                    timeout=self.cfg.health_timeout)
            report.http_status = response.status
            if response.status >= 500:
                report.detail = f"airsaned respondio HTTP {response.status}"
                self.last_report = report
                return report
        except ESCLError as exc:
            report.detail = f"airsaned no responde en {self.cfg.base_url}: {exc}"
            self.last_report = report
            return report

        # El puerto contesta; confirmamos que ademas hay un escaner utilizable.
        try:
            report.scanner_url = self.client.resolve_scanner()
            status = self.client.status()
            report.scanner_state = status.get("state")
            report.healthy = True
            report.detail = f"ok ({report.scanner_state or 'estado desconocido'})"
        except ESCLError as exc:
            # El escaner puede tardar en aparecer tras un reinicio de airsaned.
            self.client.invalidate()
            report.detail = f"airsaned esta arriba pero sin escaner utilizable: {exc}"

        self.last_report = report
        return report

    def wait_until_healthy(self, timeout: float | None = None,
                           on_wait: Callable[[HealthReport, float], None] | None = None,
                           abort: Callable[[], bool] | None = None,
                           sleeper: Callable[[float], Any] | None = None
                           ) -> HealthReport:
        """Espera activamente a que airsaned vuelva (lo reinicia systemd).

        Devuelve el ultimo informe: sano si se recupero, insano si expiro el
        plazo o si `abort` pidio salir (parada del servicio, cancelacion).
        """
        limit = self.cfg.health_wait if timeout is None else timeout
        report = self.check()
        if report.healthy or limit <= 0:
            return report

        sleep = sleeper or self._sleep
        deadline = self._clock() + limit
        LOG.warning("airsaned no esta sano (%s); esperando hasta %.0fs a que "
                    "systemd lo reinicie", report.detail, limit)
        attempt = 0
        while True:
            if abort is not None and abort():
                LOG.info("espera de airsaned interrumpida")
                return report
            remaining = deadline - self._clock()
            if remaining <= 0:
                LOG.error("airsaned sigue caido tras %.0fs de espera", limit)
                return report
            if on_wait is not None:
                on_wait(report, remaining)
            attempt += 1
            sleep(min(self.cfg.health_poll, remaining))
            report = self.check()
            if report.healthy:
                LOG.info("airsaned recuperado tras %d comprobaciones (%s)",
                         attempt, report.detail)
                return report
