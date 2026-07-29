"""Modelo de datos de los trabajos de escaneo."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

# La G2010 anuncia 75/150/300/600/1200 ppp por eSCL. Aceptamos cualquier valor
# del rango y dejamos que el backend elija el mas cercano soportado.
MIN_DPI = 50
MAX_DPI = 1200

FORMATS: dict[str, tuple[str, str]] = {
    # alias -> (mime, extension)
    "pdf": ("application/pdf", "pdf"),
    "jpeg": ("image/jpeg", "jpg"),
    "jpg": ("image/jpeg", "jpg"),
    "png": ("image/png", "png"),
    "tiff": ("image/tiff", "tiff"),
    "tif": ("image/tiff", "tiff"),
}

MODES: dict[str, str] = {
    # alias -> ColorMode eSCL
    "color": "RGB24",
    "colour": "RGB24",
    "rgb": "RGB24",
    "rgb24": "RGB24",
    "gray": "Grayscale8",
    "grey": "Grayscale8",
    "grayscale": "Grayscale8",
    "grayscale8": "Grayscale8",
    "lineart": "BlackAndWhite1",
    "bw": "BlackAndWhite1",
    "blackandwhite1": "BlackAndWhite1",
}

SOURCES: dict[str, str] = {
    "platen": "Platen",
    "flatbed": "Platen",
    "cristal": "Platen",
    "adf": "Feeder",
    "feeder": "Feeder",
}

# Tamaños de pagina en 1/300 de pulgada (unidad de region eSCL).
PAGE_SIZES: dict[str, tuple[int, int]] = {
    "a4": (2480, 3508),
    "letter": (2550, 3300),
    "legal": (2550, 4200),
    "a5": (1748, 2480),
    "a6": (1240, 1748),
}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_BACKEND = "waiting_backend"
    RETRYING = "retrying"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (JobState.DONE, JobState.FAILED, JobState.CANCELLED)


class ValidationError(ValueError):
    """Parametros de trabajo invalidos (respuesta 400)."""


def normalize_format(value: str) -> str:
    key = str(value or "").strip().lower().lstrip(".")
    if key not in FORMATS:
        raise ValidationError(
            f"formato invalido: {value!r} (validos: {', '.join(sorted(set(FORMATS)))})")
    return key


def normalize_mode(value: str) -> str:
    key = str(value or "").strip().lower()
    if key not in MODES:
        raise ValidationError(
            f"modo invalido: {value!r} (validos: {', '.join(sorted(set(MODES)))})")
    return key


def normalize_source(value: str) -> str:
    key = str(value or "").strip().lower()
    if key not in SOURCES:
        raise ValidationError(
            f"fuente invalida: {value!r} (validos: {', '.join(sorted(set(SOURCES)))})")
    return SOURCES[key]


def normalize_page(value: str) -> str:
    key = str(value or "").strip().lower()
    if not key or key in ("max", "full", "auto"):
        return ""
    if key not in PAGE_SIZES:
        raise ValidationError(
            f"tamaño de pagina invalido: {value!r} (validos: max, {', '.join(sorted(PAGE_SIZES))})")
    return key


def normalize_dpi(value: Any) -> int:
    try:
        dpi = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"dpi invalido: {value!r}") from exc
    if not MIN_DPI <= dpi <= MAX_DPI:
        raise ValidationError(f"dpi fuera de rango ({MIN_DPI}-{MAX_DPI}): {dpi}")
    return dpi


def sanitize_name(value: str, fallback: str = "") -> str:
    """Convierte un nombre libre en algo seguro para un nombre de fichero."""
    cleaned = _SAFE_NAME.sub("_", str(value or "").strip()).strip("._-")
    return cleaned[:64] or fallback


def mime_for(fmt: str) -> str:
    return FORMATS[normalize_format(fmt)][0]


def extension_for(fmt: str) -> str:
    return FORMATS[normalize_format(fmt)][1]


def escl_color_mode(mode: str) -> str:
    return MODES[normalize_mode(mode)]


@dataclass
class Job:
    """Un trabajo de escaneo y todo su ciclo de vida."""

    id: str
    dpi: int
    format: str
    mode: str
    source: str
    page: str = ""
    name: str = ""
    state: JobState = JobState.QUEUED
    attempts: int = 0
    max_attempts: int = 3
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    next_attempt_at: float | None = None
    output_path: str | None = None
    output_bytes: int | None = None
    error: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    client: str = ""

    @classmethod
    def create(cls, *, dpi: int, format: str, mode: str, source: str, page: str = "",
               name: str = "", max_attempts: int = 3, client: str = "") -> "Job":
        return cls(
            id=uuid.uuid4().hex[:12],
            dpi=normalize_dpi(dpi),
            format=normalize_format(format),
            mode=normalize_mode(mode),
            source=normalize_source(source),
            page=normalize_page(page),
            name=sanitize_name(name),
            max_attempts=max(1, int(max_attempts)),
            client=client,
        )

    def note(self, event: str, **extra: Any) -> None:
        entry: dict[str, Any] = {"at": time.time(), "event": event}
        entry.update(extra)
        self.history.append(entry)
        # El historial es para diagnostico, no para archivo: acotado en memoria.
        if len(self.history) > 50:
            del self.history[:-50]

    @property
    def extension(self) -> str:
        return extension_for(self.format)

    @property
    def mime(self) -> str:
        return mime_for(self.format)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        payload = dict(data)
        payload["state"] = JobState(payload.get("state", "queued"))
        payload.setdefault("history", [])
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known})
