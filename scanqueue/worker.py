"""Cola de trabajos con un unico hilo trabajador.

Un solo trabajo a la vez: la G2010 por USB no admite escaneos concurrentes y
AirSane devolveria 409. Antes de cada intento se comprueba airsaned y, si esta
caido, se espera activamente a que systemd lo reinicie. Los fallos transitorios
se reintentan con backoff exponencial.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from typing import Any

from .backends import ScanBackend
from .config import Config
from .escl import ESCLClient, ESCLError
from .health import HealthMonitor
from .imaging import ImagingError, coerce_format
from .logging_setup import AuditLog
from .models import Job, JobState
from .output import OutputError, run_post_command, write_result
from .store import JobStore

LOG = logging.getLogger("scanqueue.worker")


class QueueFull(RuntimeError):
    """La cola alcanzo su tamaño maximo."""


class ScanWorker:
    """Cola FIFO persistente servida por un unico hilo."""

    def __init__(self, config: Config, store: JobStore, backend: ScanBackend,
                 health: HealthMonitor, client: ESCLClient,
                 audit: AuditLog | None = None) -> None:
        self.config = config
        self.store = store
        self.backend = backend
        self.health = health
        self.client = client
        self.audit = audit

        self._queue: deque[str] = deque()
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._wake = threading.Event()  # interrumpe esperas de backoff
        self._thread: threading.Thread | None = None
        self._current: str | None = None
        self._cancelled: set[str] = set()
        self._started_at = time.time()
        self.counters: dict[str, int] = {
            "submitted": 0, "completed": 0, "failed": 0,
            "cancelled": 0, "retries": 0, "backend_waits": 0,
        }

    # ------------------------------------------------------------- ciclo de vida

    def start(self) -> None:
        if self._thread is not None:
            return
        self.recover()
        self._thread = threading.Thread(target=self._run, name="scanqueue-worker",
                                        daemon=True)
        self._thread.start()
        LOG.info("hilo trabajador arrancado")

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        with self._condition:
            self._condition.notify_all()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                LOG.warning("el hilo trabajador no termino en %.0fs", timeout)

    def recover(self) -> None:
        """Vuelve a encolar los trabajos que quedaron a medias tras un reinicio."""
        recovered = 0
        for job in self.store.pending():
            if job.state is JobState.RUNNING:
                # Estaba escaneando cuando el proceso murio: cuenta como intento
                # gastado, no repetimos infinitamente algo que quiza cuelga.
                job.note("recuperado", previous_state=job.state.value)
                LOG.warning("trabajo %s estaba en ejecucion al reiniciar; se reencola "
                            "(intentos gastados: %d)", job.id, job.attempts)
            job.state = JobState.QUEUED
            job.next_attempt_at = None
            self.store.save(job)
            self._queue.append(job.id)
            recovered += 1
        if recovered:
            LOG.info("%d trabajo(s) recuperados de la cola persistente", recovered)
            self._audit("queue.recovered", count=recovered)

    # ------------------------------------------------------------------ API

    def submit(self, job: Job) -> Job:
        with self._condition:
            if len(self._queue) >= self.config.service.max_queue:
                raise QueueFull(
                    f"la cola esta llena ({self.config.service.max_queue} trabajos)")
            job.state = JobState.QUEUED
            job.note("encolado", position=len(self._queue) + 1)
            self.store.save(job)
            self._queue.append(job.id)
            self.counters["submitted"] += 1
            self._condition.notify()
        LOG.info("trabajo %s encolado (%d ppp, %s, %s)", job.id, job.dpi, job.format,
                 job.mode)
        self._audit("job.submitted", job_id=job.id, dpi=job.dpi, format=job.format,
                    mode=job.mode, source=job.source, client=job.client)
        return job

    def cancel(self, job_id: str) -> Job | None:
        job = self.store.get(job_id)
        if job is None or job.state.terminal:
            return job
        with self._condition:
            if job_id in self._queue:
                self._queue.remove(job_id)
            self._cancelled.add(job_id)
        if self._current != job_id:
            job.state = JobState.CANCELLED
            job.finished_at = time.time()
            job.error = "cancelado por el usuario"
            job.note("cancelado")
            self.store.save(job)
            self.counters["cancelled"] += 1
            self._audit("job.cancelled", job_id=job.id)
        else:
            job.note("cancelacion solicitada")
            self.store.save(job)
        self._wake.set()
        return self.store.get(job_id)

    def position_of(self, job_id: str) -> int | None:
        with self._condition:
            if job_id == self._current:
                return 0
            try:
                return self._queue.index(job_id) + 1
            except ValueError:
                return None

    def stats(self) -> dict[str, Any]:
        with self._condition:
            depth, current = len(self._queue), self._current
        return {
            "queued": depth,
            "current_job": current,
            "running": current is not None,
            "uptime_seconds": round(time.time() - self._started_at, 1),
            "counters": dict(self.counters),
            "totals_by_state": self.store.counts(),
        }

    # --------------------------------------------------------------- interno

    def _audit(self, event: str, **fields: Any) -> None:
        if self.audit is not None:
            self.audit.emit(event, **fields)

    def _sleep(self, seconds: float) -> bool:
        """Espera interrumpible. False si hay que abortar (parada o cancelacion)."""
        self._wake.clear()
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return not self._stop.is_set()
            if self._wake.wait(min(remaining, 1.0)):
                self._wake.clear()
                return False
            if self._stop.is_set():
                return False

    def _next_job_id(self) -> str | None:
        with self._condition:
            while not self._queue and not self._stop.is_set():
                self._condition.wait(timeout=1.0)
            if self._stop.is_set() and not self._queue:
                return None
            return self._queue.popleft() if self._queue else None

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self._next_job_id()
            if job_id is None:
                continue
            job = self.store.get(job_id)
            if job is None:
                LOG.warning("el trabajo %s desaparecio del almacen", job_id)
                continue
            if job_id in self._cancelled or job.state is JobState.CANCELLED:
                self._finish_cancelled(job)
                continue
            with self._condition:
                self._current = job_id
            try:
                self._process(job)
            except Exception:  # pragma: no cover - red de seguridad del hilo
                LOG.exception("fallo no controlado procesando %s", job_id)
                job.state = JobState.FAILED
                job.error = "error interno del servicio"
                job.finished_at = time.time()
                try:
                    self.store.save(job)
                except Exception:
                    LOG.warning("no se pudo registrar el fallo de %s", job_id)
                self.counters["failed"] += 1
            finally:
                with self._condition:
                    self._current = None
                self._cancelled.discard(job_id)
        LOG.info("hilo trabajador detenido")

    def _finish_cancelled(self, job: Job) -> None:
        job.state = JobState.CANCELLED
        job.finished_at = time.time()
        job.error = job.error or "cancelado por el usuario"
        job.note("cancelado")
        self.store.save(job)
        self.counters["cancelled"] += 1
        self._audit("job.cancelled", job_id=job.id)

    def _is_cancelled(self, job: Job) -> bool:
        return job.id in self._cancelled

    def _wait_for_backend(self, job: Job) -> bool:
        """Comprueba airsaned antes del intento; espera si esta caido."""
        report = self.health.check()
        if report.healthy:
            return True

        self.counters["backend_waits"] += 1
        job.state = JobState.WAITING_BACKEND
        job.note("esperando_backend", detail=report.detail)
        self.store.save(job)
        self._audit("backend.unhealthy", job_id=job.id, detail=report.detail,
                    systemd_state=report.systemd_state)
        LOG.warning("trabajo %s en espera: %s", job.id, report.detail)

        # El escaner pudo cambiar de URL al reiniciarse airsaned.
        self.client.invalidate()
        # La espera se corta si paramos el servicio o si cancelan el trabajo:
        # de lo contrario el hilo seguiria dormido despues del cierre.
        report = self.health.wait_until_healthy(
            abort=lambda: self._stop.is_set() or self._is_cancelled(job),
            sleeper=self._sleep)
        if report.healthy:
            self._audit("backend.recovered", job_id=job.id, detail=report.detail)
            return True
        self._audit("backend.timeout", job_id=job.id, detail=report.detail)
        return False

    def _backoff_delay(self, attempt: int) -> float:
        cfg = self.config.scan
        delay = cfg.backoff_base * (cfg.backoff_factor ** (attempt - 1))
        delay = min(delay, cfg.backoff_max) if cfg.backoff_max else delay
        # Jitter: evita que varios reintentos caigan a la vez sobre el USB.
        return max(0.0, delay * (0.8 + random.random() * 0.4))

    def _process(self, job: Job) -> None:
        max_attempts = min(job.max_attempts, self.config.scan.max_attempts)
        job.started_at = job.started_at or time.time()

        while job.attempts < max_attempts:
            if self._stop.is_set():
                # Se queda en cola: al arrancar de nuevo, recover() lo retoma.
                job.state = JobState.QUEUED
                job.note("aplazado_por_parada")
                self.store.save(job)
                with self._condition:
                    self._queue.appendleft(job.id)
                return
            if self._is_cancelled(job):
                self._finish_cancelled(job)
                return

            if not self._wait_for_backend(job):
                if self._stop.is_set() or self._is_cancelled(job):
                    # Parada o cancelacion: la cabecera del bucle lo resuelve
                    # sin gastar un intento.
                    continue
                job.attempts += 1
                self._register_failure(
                    job, "airsaned no volvio a estar disponible a tiempo",
                    max_attempts)
                if job.state is JobState.FAILED:
                    return
                continue

            job.attempts += 1
            job.state = JobState.RUNNING
            job.note("intento_iniciado", attempt=job.attempts)
            self.store.save(job)
            self._audit("job.attempt", job_id=job.id, attempt=job.attempts,
                        max_attempts=max_attempts)
            LOG.info("trabajo %s: intento %d/%d", job.id, job.attempts, max_attempts)

            started = time.time()
            deadline = started + self.config.scan.job_timeout
            try:
                pages = self.backend.scan(job, deadline)
                data = coerce_format(pages, job.extension, job.dpi)
            except ESCLError as exc:
                self.client.invalidate()
                if not exc.retryable:
                    LOG.error("trabajo %s: error no reintentable: %s", job.id, exc)
                    self._register_failure(job, str(exc), max_attempts, force=True)
                    return
                self._register_failure(job, str(exc), max_attempts)
                if job.state is JobState.FAILED:
                    return
                continue
            except ImagingError as exc:
                LOG.error("trabajo %s: no se pudo generar %s: %s", job.id, job.format, exc)
                self._register_failure(job, str(exc), max_attempts, force=True)
                return

            elapsed = time.time() - started
            if self._is_cancelled(job):
                # Ya escaneado: guardarlo igualmente seria confuso, se descarta.
                self._finish_cancelled(job)
                return

            try:
                result = write_result(self.config, job, data)
            except OutputError as exc:
                LOG.error("trabajo %s: %s", job.id, exc)
                self._register_failure(job, str(exc), max_attempts, force=True)
                return

            run_post_command(self.config.scan.post_command, job, result.path)

            job.state = JobState.DONE
            job.output_path = str(result.path)
            job.output_bytes = result.size
            job.finished_at = time.time()
            job.error = result.note if result.fallback else None
            job.note("completado", seconds=round(elapsed, 2), bytes=result.size,
                     path=str(result.path), fallback=result.fallback)
            self.store.save(job)
            self.counters["completed"] += 1
            LOG.info("trabajo %s completado en %.1fs -> %s (%d bytes)", job.id,
                     elapsed, result.path, result.size)
            self._audit("job.completed", job_id=job.id, seconds=round(elapsed, 2),
                        path=str(result.path), bytes=result.size,
                        attempts=job.attempts, fallback=result.fallback)
            return

        self._register_failure(job, job.error or "se agotaron los intentos",
                               max_attempts, force=True)

    def _register_failure(self, job: Job, error: str, max_attempts: int,
                          force: bool = False) -> None:
        """Anota un intento fallido y decide si reintentar o rendirse."""
        job.error = error
        job.note("intento_fallido", attempt=job.attempts, error=error)
        self.counters["retries"] += 0 if force else 1
        self._audit("job.attempt_failed", job_id=job.id, attempt=job.attempts,
                    error=error, will_retry=not force and job.attempts < max_attempts)

        if force or job.attempts >= max_attempts:
            job.state = JobState.FAILED
            job.finished_at = time.time()
            job.next_attempt_at = None
            self.store.save(job)
            self.counters["failed"] += 1
            LOG.error("trabajo %s fallido tras %d intento(s): %s", job.id,
                      job.attempts, error)
            self._audit("job.failed", job_id=job.id, attempts=job.attempts, error=error)
            return

        delay = self._backoff_delay(job.attempts)
        job.state = JobState.RETRYING
        job.next_attempt_at = time.time() + delay
        self.store.save(job)
        LOG.warning("trabajo %s: intento %d fallido (%s); reintento en %.1fs",
                    job.id, job.attempts, error, delay)
        # La espera de backoff se corta si paran el servicio o cancelan: la
        # cabecera del bucle de _process se encarga de ambos casos.
        self._sleep(delay)
