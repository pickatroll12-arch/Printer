"""Fachada del servicio: une configuracion, almacen, backend, salud y cola.

Tanto la API HTTP como el socket UNIX hablan con esta clase, de modo que ambas
interfaces se comportan exactamente igual.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .backends import build_backend
from .config import Config
from .escl import ESCLClient, ESCLError
from .health import HealthMonitor
from .logging_setup import AuditLog, setup_logging
from .models import Job, JobState, ValidationError
from .store import JobStore
from .worker import QueueFull, ScanWorker

LOG = logging.getLogger("scanqueue.service")


class NotFound(LookupError):
    """El trabajo pedido no existe."""


class ScanService:
    def __init__(self, config: Config) -> None:
        self.config = config
        config.service.state_dir.mkdir(parents=True, exist_ok=True)
        # Idempotente: `serve` ya lo hizo, pero asi el servicio tambien registra
        # correctamente cuando se usa embebido (pruebas, scripts).
        setup_logging(config.logging)
        self.audit = AuditLog(config.logging.audit_file)
        self.store = JobStore(config.service.state_dir / "jobs.db")
        self.client = ESCLClient(config.airsane.base_url,
                                 scanner=config.airsane.scanner,
                                 timeout=config.airsane.health_timeout)
        self.health = HealthMonitor(config.airsane, self.client)
        self.backend = build_backend(config, self.client)
        self.worker = ScanWorker(config, self.store, self.backend, self.health,
                                 self.client, self.audit)

    # ------------------------------------------------------------- ciclo de vida

    def start(self) -> None:
        self._ensure_output_dir()
        self._purge_history()
        self.worker.start()
        self.audit.emit("service.started", backend=self.backend.name,
                        output_dir=str(self.config.output.dir),
                        airsane=self.config.airsane.base_url)

    def stop(self) -> None:
        self.worker.stop()
        self.store.close()
        self.audit.emit("service.stopped")

    def _ensure_output_dir(self) -> None:
        try:
            self.config.output.dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # No es fatal: puede ser un montaje que aparezca mas tarde; el
            # trabajador tiene spool de reserva.
            LOG.warning("no se pudo preparar la carpeta de salida %s: %s",
                        self.config.output.dir, exc)

    def _purge_history(self) -> None:
        days = self.config.service.history_days
        if days <= 0:
            return
        removed = self.store.purge_older_than(days * 86400)
        if removed:
            LOG.info("purgados %d registros de historial (> %d dias)", removed, days)

    # ------------------------------------------------------------------ acciones

    def submit(self, params: dict[str, Any], client: str = "") -> Job:
        """Crea y encola un trabajo a partir de parametros del cliente."""
        scan = self.config.scan
        job = Job.create(
            dpi=params.get("dpi", scan.default_dpi),
            format=params.get("format", scan.default_format),
            mode=params.get("mode", scan.default_mode),
            source=params.get("source", scan.default_source),
            page=params.get("page", scan.default_page),
            name=params.get("name", ""),
            max_attempts=int(params.get("max_attempts", scan.max_attempts)),
            client=client,
        )
        return self.worker.submit(job)

    def get(self, job_id: str) -> Job:
        job = self.store.get(job_id)
        if job is None:
            raise NotFound(f"trabajo desconocido: {job_id}")
        return job

    def job_view(self, job: Job) -> dict[str, Any]:
        data = job.to_dict()
        position = self.worker.position_of(job.id)
        if position is not None:
            data["queue_position"] = position
        return data

    def list(self, state: str = "", limit: int = 50, offset: int = 0) -> list[Job]:
        states = None
        if state:
            try:
                states = [JobState(state)]
            except ValueError as exc:
                valid = ", ".join(s.value for s in JobState)
                raise ValidationError(
                    f"estado invalido: {state!r} (validos: {valid})") from exc
        return self.store.list(states=states, limit=limit, offset=offset)

    def cancel(self, job_id: str) -> Job:
        job = self.worker.cancel(job_id)
        if job is None:
            raise NotFound(f"trabajo desconocido: {job_id}")
        return job

    def result_path(self, job_id: str) -> Path:
        job = self.get(job_id)
        if job.state is not JobState.DONE or not job.output_path:
            raise NotFound(f"el trabajo {job_id} todavia no tiene resultado")
        path = Path(job.output_path)
        if not path.is_file():
            raise NotFound(f"el fichero de {job_id} ya no existe: {path}")
        return path

    # -------------------------------------------------------------- diagnostico

    def health_view(self) -> dict[str, Any]:
        report = self.health.check()
        return {
            "service": "ok",
            "backend": self.backend.name,
            "airsane": report.to_dict(),
            "queue": self.worker.stats(),
            "output_dir": str(self.config.output.dir),
            "output_writable": self._output_writable(),
        }

    def _output_writable(self) -> bool:
        import os

        try:
            return os.access(self.config.output.dir, os.W_OK)
        except OSError:
            return False

    def capabilities_view(self) -> dict[str, Any]:
        try:
            caps = self.client.capabilities(force=True)
        except ESCLError as exc:
            return {"available": False, "error": str(exc)}
        return {"available": True, "scanner_url": self.client.resolve_scanner(),
                **caps.to_dict()}

    def info_view(self) -> dict[str, Any]:
        from . import __version__

        return {
            "version": __version__,
            "started_at": round(time.time() - self.worker.stats()["uptime_seconds"], 1),
            "config": self.config.describe(),
        }


__all__ = ["ScanService", "NotFound", "QueueFull", "ValidationError"]
