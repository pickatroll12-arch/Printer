"""Backends de escaneo: eSCL (recomendado) y scanimage (respaldo)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from typing import Protocol

from .config import Config
from .escl import ESCLClient, ESCLError, ESCLTimeout
from .models import Job, escl_color_mode

LOG = logging.getLogger("scanqueue.backend")

# Equivalencia de nuestros modos con los que entiende `scanimage`.
SANE_MODES = {"RGB24": "Color", "Grayscale8": "Gray", "BlackAndWhite1": "Lineart"}


class ScanBackend(Protocol):
    name: str

    def scan(self, job: Job, deadline: float) -> list[bytes]:
        """Escanea y devuelve las paginas en bytes. Lanza ESCLError si falla."""


class ESCLBackend:
    """Escanea a traves de AirSane. No toca el USB directamente."""

    name = "escl"

    def __init__(self, config: Config, client: ESCLClient) -> None:
        self.config = config
        self.client = client

    def scan(self, job: Job, deadline: float) -> list[bytes]:
        # AirSane genera PDF por si mismo en muchas configuraciones; si no lo
        # anuncia, pedimos JPEG y lo envolvemos nosotros (ver imaging.py).
        mime = job.mime
        try:
            caps = self.client.capabilities()
            if not caps.supports_format(mime):
                LOG.info("el escaner no anuncia %s; se pedira image/jpeg", mime)
                mime = "image/jpeg"
        except ESCLError as exc:
            LOG.debug("capacidades no disponibles (%s); se pide %s tal cual", exc, mime)

        return self.client.scan(
            dpi=job.dpi,
            mime=mime,
            color_mode=escl_color_mode(job.mode),
            source=job.source,
            page=job.page or self.config.scan.default_page,
            deadline=deadline,
            max_pages=1 if job.source == "Platen" else 50,
        )


class ScanimageBackend:
    """Respaldo con SANE directo.

    Solo tiene sentido si airsaned NO esta corriendo: ambos se pelean por el
    mismo dispositivo USB.
    """

    name = "scanimage"

    def __init__(self, config: Config) -> None:
        self.config = config

    def _command(self, job: Job, image_format: str) -> list[str]:
        command = ["scanimage", "--format", image_format,
                   "--resolution", str(job.dpi),
                   "--mode", SANE_MODES.get(escl_color_mode(job.mode), "Color")]
        if self.config.scan.scanimage_device:
            command += ["-d", self.config.scan.scanimage_device]
        return command

    def scan(self, job: Job, deadline: float) -> list[bytes]:
        if not shutil.which("scanimage"):
            raise ESCLError("scanimage no esta instalado (paquete sane-utils)",
                            retryable=False)
        timeout = max(5.0, deadline - time.time())
        last_error: Exception | None = None
        for image_format in ("jpeg", "tiff"):
            command = self._command(job, image_format)
            LOG.debug("ejecutando %s", " ".join(command))
            try:
                result = subprocess.run(command, capture_output=True, timeout=timeout,
                                        check=False)
            except subprocess.TimeoutExpired as exc:
                raise ESCLTimeout(f"scanimage excedio {timeout:.0f}s") from exc
            except OSError as exc:
                raise ESCLError(f"no se pudo ejecutar scanimage: {exc}") from exc
            if result.returncode == 0 and result.stdout:
                return [result.stdout]
            detail = result.stderr[:300].decode("utf-8", "replace").strip()
            last_error = ESCLError(
                f"scanimage fallo (codigo {result.returncode}): {detail}")
            if "format" not in detail.lower():
                break
        raise last_error or ESCLError("scanimage no devolvio ninguna imagen")


def build_backend(config: Config, client: ESCLClient) -> ScanBackend:
    if config.scan.backend == "scanimage":
        return ScanimageBackend(config)
    return ESCLBackend(config, client)
