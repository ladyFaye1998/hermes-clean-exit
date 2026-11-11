"""SQLite ledger: runs, the files each run was observed writing, and planned archive locations.

It stores file names, sizes and SHA-256 digests. It never stores file content. Every operation
opens its own short-lived connection, so the ledger is safe to share between threads and between
the processes of one Hermes profile.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Optional, Sequence

from . import paths

TRACKING = "tracking"
REVIEW = "review"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    folder TEXT NOT NULL,
    folder_dev TEXT NOT NULL,
    folder_ino TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('tracking', 'review')),
    session_id TEXT,
    started_at REAL NOT NULL,
    finished_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_tracking_run ON runs (status) WHERE status = 'tracking';
CREATE TABLE IF NOT EXISTS files (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL REFERENCES runs (id),
    rel_path TEXT NOT NULL,
    rel_key TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    file_dev TEXT,
    file_ino TEXT,
    archive_rel TEXT,
    tool_call_id TEXT NOT NULL,
    recorded_at REAL NOT NULL,
    UNIQUE (run_id, rel_key)
);
PRAGMA user_version = 1;
"""
_RUN_COLUMNS = "id, folder, folder_dev, folder_ino, status, session_id"
_FILE_COLUMNS = "id, run_id, rel_path, size, sha256, archive_rel, file_dev, file_ino"


@dataclass(frozen=True)
class Run:
    id: str
    folder: str
    folder_dev: str
    folder_ino: str
    status: str
    session_id: Optional[str]


@dataclass(frozen=True)
class FileRecord:
    id: str
    run_id: str
    rel_path: str
    size: int
    sha256: str
    archive_rel: Optional[str]
    file_dev: Optional[str] = None
    file_ino: Optional[str] = None

    @property
    def identity(self) -> Optional[tuple[str, str]]:
        if self.file_dev is None or self.file_ino is None:
            return None
        return self.file_dev, self.file_ino

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(self.rel_path.split("/"))

    @property
    def archive_parts(self) -> Optional[tuple[str, ...]]:
        return tuple(self.archive_rel.split("/")) if self.archive_rel else None


class ActiveRunExists(Exception):
    def __init__(self, run: Run):
        super().__init__(run.id)
        self.run = run


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return os.path.isfile(self.path)

    @contextmanager
    def _transaction(self, write: bool) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] < 1:
                connection.executescript(_SCHEMA)
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    # -- reads ---------------------------------------------------------------------------------

    def runs(self) -> list[Run]:
        """Every run, newest first."""
        if not self.exists():
            return []
        with self._transaction(write=False) as db:
            return [Run(*row) for row in db.execute(f"SELECT {_RUN_COLUMNS} FROM runs ORDER BY seq DESC")]

    def run(self, run_id: str) -> Optional[Run]:
        if not self.exists():
            return None
        with self._transaction(write=False) as db:
            return _run(db, "id = ?", (run_id,))

    def tracking_run(self) -> Optional[Run]:
        if not self.exists():
            return None
        with self._transaction(write=False) as db:
            return _run(db, "status = ?", (TRACKING,))

    def files(self, run_id: str) -> list[FileRecord]:
        """A run's recorded files in the order they were first written."""
        if not self.exists():
            return []
        with self._transaction(write=False) as db:
            rows = db.execute(f"SELECT {_FILE_COLUMNS} FROM files WHERE run_id = ? ORDER BY seq", (run_id,))
            return [FileRecord(*row) for row in rows]

    def file_at(self, run_id: str, parts: Sequence[str]) -> Optional[FileRecord]:
        if not self.exists():
            return None
        with self._transaction(write=False) as db:
            row = db.execute(f"SELECT {_FILE_COLUMNS} FROM files WHERE run_id = ? AND rel_key = ?",
                             (run_id, paths.rel_key(parts))).fetchone()
            return FileRecord(*row) if row else None

    # -- writes --------------------------------------------------------------------------------

    def start_run(self, folder: paths.RegisteredFolder, session_id: Optional[str]) -> Run:
        """Open a tracking run. Raises ActiveRunExists while another run is tracking."""
        with self._transaction(write=True) as db:
            active = _run(db, "status = ?", (TRACKING,))
            if active is not None:
                raise ActiveRunExists(active)
            run = Run(secrets.token_hex(8), folder.path, folder.dev, folder.ino, TRACKING, session_id)
            db.execute(
                "INSERT INTO runs (id, folder, folder_dev, folder_ino, status, session_id, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run.id, run.folder, run.folder_dev, run.folder_ino, run.status, run.session_id, time.time()))
            return run

    def finish_run(self, run_id: str) -> Optional[Run]:
        """Move a run to review (a run already in review stays there). None for an unknown run."""
        with self._transaction(write=True) as db:
            db.execute("UPDATE runs SET status = ?, finished_at = ? WHERE id = ? AND status = ?",
                       (REVIEW, time.time(), run_id, TRACKING))
            return _run(db, "id = ?", (run_id,))

    def record_write(self, run_id: str, session_id: str, parts: Sequence[str], size: int, sha256: str,
                     tool_call_id: str, identity: Optional[tuple[str, str]] = None) -> bool:
        """Record an observed new write, binding an unbound run to ``session_id`` in the same
        transaction. False when the run stopped tracking or belongs to another session."""
        with self._transaction(write=True) as db:
            run = _run(db, "id = ? AND status = ?", (run_id, TRACKING))
            if run is None or (run.session_id is not None and run.session_id != session_id):
                return False
            if run.session_id is None:
                db.execute("UPDATE runs SET session_id = ? WHERE id = ?", (session_id, run_id))
            file_dev, file_ino = identity or (None, None)
            db.execute(
                "INSERT INTO files (id, run_id, rel_path, rel_key, size, sha256, file_dev, file_ino, tool_call_id, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (run_id, rel_key) DO UPDATE SET rel_path = excluded.rel_path, "
                "size = excluded.size, sha256 = excluded.sha256, file_dev = excluded.file_dev, "
                "file_ino = excluded.file_ino, tool_call_id = excluded.tool_call_id, "
                "recorded_at = excluded.recorded_at",
                (secrets.token_hex(8), run_id, paths.rel_path(parts), paths.rel_key(parts), size, sha256,
                 file_dev, file_ino, tool_call_id, time.time()))
            return True

    def plan_archive(self, run_id: str, destinations: Mapping[str, str]) -> None:
        """Persist where each selected file is about to be moved. Committed before any move."""
        with self._transaction(write=True) as db:
            for file_id, archive_rel in destinations.items():
                db.execute("UPDATE files SET archive_rel = ? WHERE id = ? AND run_id = ?",
                           (archive_rel, file_id, run_id))


def _run(db: sqlite3.Connection, where: str, values: tuple) -> Optional[Run]:
    row = db.execute(f"SELECT {_RUN_COLUMNS} FROM runs WHERE {where}", values).fetchone()
    return Run(*row) if row else None
