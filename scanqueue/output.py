"""Escritura del resultado en la carpeta de Nextcloud."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .models import Job

LOG = logging.getLogger("scanqueue.output")

PLACEHOLDERS = ("{date}", "{time}", "{timestamp}", "{job_id}", "{dpi}",
                "{format}", "{ext}", "{mode}", "{name}")


class OutputError(RuntimeError):
    """No se pudo entregar el fichero resultante."""


@dataclass
class WriteResult:
    path: Path
    size: int
    fallback: bool = False

    @property
    def note(self) -> str:
        if self.fallback:
            return (f"la carpeta de Nextcloud no estaba disponible; guardado en "
                    f"{self.path}")
        return f"guardado en {self.path}"


def render_filename(template: str, job: Job, when: float | None = None) -> str:
    """Aplica la plantilla de nombre. Un nombre invalido nunca aborta el trabajo."""
    moment = time.localtime(when if when is not None else time.time())
    values = {
        "date": time.strftime("%Y%m%d", moment),
        "time": time.strftime("%H%M%S", moment),
        "timestamp": str(int(when if when is not None else time.time())),
        "job_id": job.id,
        "dpi": str(job.dpi),
        "format": job.format,
        "ext": job.extension,
        "mode": job.mode,
        "name": job.name or "scan",
    }
    try:
        rendered = template.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        LOG.warning("plantilla de nombre invalida (%s): %s; se usa la de por defecto",
                    template, exc)
        rendered = "scan_{date}_{time}_{job_id}.{ext}".format(**values)

    # Nunca dejamos que la plantilla escape del directorio de salida.
    rendered = rendered.replace("\x00", "").strip().lstrip(".")
    rendered = Path(rendered).name
    return rendered or f"scan_{job.id}.{job.extension}"


def unique_path(directory: Path, filename: str) -> Path:
    """Evita pisar ficheros existentes añadiendo un sufijo -1, -2, ..."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(1, 1000):
        alternative = directory / f"{stem}-{index}{suffix}"
        if not alternative.exists():
            return alternative
    raise OutputError(f"demasiados ficheros con el nombre {filename}")


def _atomic_write(directory: Path, filename: str, data: bytes, mode: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = unique_path(directory, filename)
    # El temporal va en el mismo directorio para que os.replace sea atomico y
    # el cliente de Nextcloud nunca vea un fichero a medias.
    temporary = target.with_name(target.name + ".part")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - limpieza best-effort
            pass
        raise
    return target


def write_result(config: Config, job: Job, data: bytes) -> WriteResult:
    """Guarda el escaneo. Si Nextcloud no esta disponible, usa un spool local.

    Perder un escaneo ya hecho es peor que guardarlo en otro sitio: el usuario
    tendria que volver a poner el papel en el cristal.
    """
    filename = render_filename(config.output.filename_template, job)
    try:
        target = _atomic_write(config.output.dir, filename, data, config.output.file_mode)
        return WriteResult(path=target, size=len(data))
    except OSError as exc:
        LOG.error("no se pudo escribir en %s (%s); se usa el spool local",
                  config.output.dir, exc)

    spool = config.service.state_dir / "spool"
    try:
        target = _atomic_write(spool, filename, data, config.output.file_mode)
    except OSError as exc:
        raise OutputError(
            f"no se pudo guardar el resultado ni en {config.output.dir} ni en "
            f"{spool}: {exc}") from exc
    return WriteResult(path=target, size=len(data), fallback=True)


def run_post_command(command: str, job: Job, path: Path, timeout: float = 30.0) -> None:
    """Hook opcional tras guardar (OCR, notificacion, `nextcloud occ`, ...)."""
    if not command:
        return
    env = dict(os.environ)
    env.update({
        "SCANQUEUE_FILE": str(path),
        "SCANQUEUE_JOB_ID": job.id,
        "SCANQUEUE_FORMAT": job.format,
        "SCANQUEUE_DPI": str(job.dpi),
    })
    try:
        result = subprocess.run(command, shell=True, env=env, capture_output=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.warning("el comando posterior fallo: %s", exc)
        return
    if result.returncode != 0:
        LOG.warning("el comando posterior devolvio %d: %s", result.returncode,
                    result.stderr[:200].decode("utf-8", "replace").strip())
