"""Persistencia de trabajos en SQLite.

Sobrevive a reinicios del servicio: los trabajos pendientes se recuperan al
arrancar. Un unico fichero, sin servidor, sin dependencias.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable

from .models import Job, JobState

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    state        TEXT NOT NULL,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
"""


class JobStore:
    """Almacen de trabajos seguro entre hilos."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            # WAL: lecturas concurrentes (API) sin bloquear al trabajador.
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def save(self, job: Job) -> None:
        payload = json.dumps(job.to_dict(), ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (id, state, created_at, updated_at, payload) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET state=excluded.state, "
                "updated_at=excluded.updated_at, payload=excluded.payload",
                (job.id, job.state.value, job.created_at, time.time(), payload),
            )
            self._conn.commit()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return Job.from_dict(json.loads(row["payload"])) if row else None

    def list(self, states: Iterable[JobState] | None = None, limit: int = 100,
             offset: int = 0) -> list[Job]:
        query = "SELECT payload FROM jobs"
        params: list[object] = []
        if states:
            values = [s.value for s in states]
            query += f" WHERE state IN ({','.join('?' * len(values))})"
            params.extend(values)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([max(1, limit), max(0, offset)])
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [Job.from_dict(json.loads(row["payload"])) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state").fetchall()
        return {row["state"]: int(row["n"]) for row in rows}

    def pending(self) -> list[Job]:
        """Trabajos no terminales, en orden FIFO (para recuperar tras reinicio)."""
        pending_states = [s.value for s in JobState if not s.terminal]
        with self._lock:
            rows = self._conn.execute(
                f"SELECT payload FROM jobs WHERE state IN "
                f"({','.join('?' * len(pending_states))}) ORDER BY created_at ASC",
                pending_states,
            ).fetchall()
        return [Job.from_dict(json.loads(row["payload"])) for row in rows]

    def purge_older_than(self, seconds: float) -> int:
        """Borra registros terminales antiguos. Devuelve cuantos se eliminaron."""
        cutoff = time.time() - seconds
        terminal = [s.value for s in JobState if s.terminal]
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM jobs WHERE state IN ({','.join('?' * len(terminal))}) "
                f"AND updated_at < ?",
                (*terminal, cutoff),
            )
            self._conn.commit()
            return cur.rowcount
