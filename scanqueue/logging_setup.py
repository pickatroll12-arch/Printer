"""Logging rotativo + pista de auditoria en JSONL."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import LoggingConfig

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(cfg: LoggingConfig) -> logging.Logger:
    """Configura el logger raiz de scanqueue. Idempotente."""
    logger = logging.getLogger("scanqueue")
    logger.setLevel(getattr(logging, cfg.level, logging.INFO))
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    cfg.file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        cfg.file, maxBytes=cfg.max_bytes, backupCount=cfg.backups, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if cfg.console:
        # Bajo systemd esto acaba en el journal; en terminal, en pantalla.
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    return logger


class AuditLog:
    """Registro append-only en JSON Lines, pensado para auditoria y scripts.

    Cada linea es un evento autocontenido; los fallos de escritura nunca
    interrumpen un trabajo (se degradan a un warning en el log normal).
    """

    def __init__(self, path: Path, logger: logging.Logger | None = None) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._logger = logger or logging.getLogger("scanqueue.audit")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._logger.warning("no se pudo crear el directorio de auditoria: %s", exc)

    def emit(self, event: str, **fields: Any) -> None:
        record: dict[str, Any] = {
            "ts": round(time.time(), 3),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "pid": os.getpid(),
            "event": event,
        }
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False, default=str)
        try:
            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
        except OSError as exc:
            self._logger.warning("fallo al escribir auditoria (%s): %s", event, exc)
