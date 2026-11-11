"""Observe native ``write_file`` calls while a run is tracking.

``before_write`` notes that a named path did not exist yet; ``after_write`` records the file only
when the same call reports success for that same path and the bytes now on disk are the bytes the
call asked for. Native writes carry no "created" flag, so this is an observed new write, not proof
of atomic creation. Anything that cannot be verified is dropped.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import fsops, paths
from .ledger import TRACKING, Ledger, Run

MAX_PENDING = 64
PENDING_TTL_S = 600.0
_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True)
class _Pending:
    run_id: str
    parts: tuple[str, ...]
    request: str                           # digest of the path and content the call named
    expected: frozenset[tuple[int, str]]   # (size, sha256) of the byte forms that content may take
    noted_at: float


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _request_digest(path: str, content: str) -> Optional[str]:
    try:
        return hashlib.sha256(path.encode("utf-8") + b"\0" + content.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        return None


def _expected_bytes(content: str, rewrite: bool) -> Optional[frozenset[tuple[int, str]]]:
    """Digests of the bytes ``content`` may be written as. A new file gets exactly its UTF-8
    encoding. Hermes keeps an existing file's CRLF line endings and BOM, so a rewrite of a file
    this run already recorded may also take those forms."""
    try:
        forms = {content.encode("utf-8")}
    except UnicodeEncodeError:
        return None
    if rewrite:
        unix = content.replace("\r\n", "\n").replace("\r", "\n")
        forms.add(unix.replace("\n", "\r\n").encode("utf-8"))
        forms |= {form if form.startswith(_BOM) else _BOM + form for form in forms}
    return frozenset((len(form), hashlib.sha256(form).hexdigest()) for form in forms)


def _reported_path(result: Any) -> Optional[str]:
    """The single absolute path a successful write_file result says it wrote, else None."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            return None
    if not isinstance(result, dict) or result.get("error"):
        return None
    resolved = result.get("resolved_path")
    if not isinstance(resolved, str) or result.get("files_modified") != [resolved]:
        return None
    return resolved


def _same_parts(a: tuple[str, ...], b: Optional[tuple[str, ...]]) -> bool:
    return b is not None and paths.rel_key(a) == paths.rel_key(b)


class WriteTracker:
    """In-memory correlation of pre and post hooks for each session and turn.

    Pending entries are bounded in number and age; an entry whose post hook never arrives (a
    blocked or crashed call) expires and records nothing.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[tuple[str, str, str, str], _Pending] = {}

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def forget_run(self, run_id: str) -> None:
        with self._lock:
            for key in [key for key, entry in self._pending.items() if entry.run_id == run_id]:
                del self._pending[key]

    def before_write(self, ledger: Ledger, args: Any, session_id: Any, tool_call_id: Any,
                     turn_id: Any = None) -> None:
        session, call = _text(session_id), _text(tool_call_id)
        if session is None or call is None or not isinstance(args, dict):
            return
        path, content = args.get("path"), args.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            return
        run = ledger.tracking_run()
        if run is None or (run.session_id is not None and run.session_id != session):
            return
        parts = paths.tracked_parts(run.folder, path)
        if parts is None or fsops.folder_problem(run.folder, run.folder_dev, run.folder_ino):
            return
        rewrite = self._is_own_rewrite(ledger, run, session, parts)
        if rewrite is None:
            return
        request, expected = _request_digest(path, content), _expected_bytes(content, rewrite)
        if request is None or expected is None:
            return
        entry = _Pending(run.id, parts, request, expected, self._clock())
        with self._lock:
            self._pending[(str(ledger.path), session, _text(turn_id) or "", call)] = entry
            self._trim(entry.noted_at)

    def _is_own_rewrite(self, ledger: Ledger, run: Run, session: str, parts: tuple[str, ...]) -> Optional[bool]:
        """False: nothing is at the path (a new write). True: the path holds, unmodified, a file this
        run's session already recorded. None: anything else, which is not recorded."""
        try:
            existing = fsops.walk(run.folder, parts)
        except (fsops.UnsafePath, OSError):
            return None
        if existing is None:
            return False
        record = ledger.file_at(run.id, parts)
        if record is None or run.session_id != session:
            return None
        intact = fsops.probe(run.folder, parts, record.size, record.sha256, record.identity) == fsops.MATCH
        return True if intact else None

    def _trim(self, now: float) -> None:
        for key in [key for key, entry in self._pending.items() if now - entry.noted_at > PENDING_TTL_S]:
            del self._pending[key]
        while len(self._pending) > MAX_PENDING:
            del self._pending[min(self._pending, key=lambda key: self._pending[key].noted_at)]

    def after_write(self, ledger: Ledger, args: Any, result: Any, status: Any, session_id: Any,
                    tool_call_id: Any, turn_id: Any = None) -> None:
        session, call = _text(session_id), _text(tool_call_id)
        if session is None or call is None:
            return
        with self._lock:
            entry = self._pending.pop((str(ledger.path), session, _text(turn_id) or "", call), None)
        if entry is None or self._clock() - entry.noted_at > PENDING_TTL_S:
            return
        if status not in (None, "", "ok") or not isinstance(args, dict):
            return
        path, content = args.get("path"), args.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            return
        if _request_digest(path, content) != entry.request:
            return
        reported = _reported_path(result)
        if reported is None:
            return
        run = ledger.run(entry.run_id)
        if run is None or run.status != TRACKING or (run.session_id is not None and run.session_id != session):
            return
        if fsops.folder_problem(run.folder, run.folder_dev, run.folder_ino):
            return
        if not _same_parts(entry.parts, paths.tracked_parts(run.folder, reported)):
            return
        if not _same_parts(entry.parts, paths.tracked_parts(run.folder, path)):
            return
        written = self._written(run, entry)
        if written is not None:
            size, sha256, identity = written
            ledger.record_write(run.id, session, entry.parts, size, sha256, call, identity)

    @staticmethod
    def _written(run: Run, entry: _Pending) -> Optional[tuple[int, str, tuple[str, str]]]:
        """Fingerprint the file now at the path when it holds the requested bytes."""
        try:
            leaf = fsops.walk(run.folder, entry.parts)
            if leaf is None or not fsops.is_plain_file(leaf) or leaf.st_nlink != 1:
                return None
            if all(leaf.st_size != expected_size for expected_size, _ in entry.expected):
                return None
            sha256, size = fsops.sha256_file(os.path.join(run.folder, *entry.parts), leaf)
        except (fsops.UnsafePath, OSError):
            return None
        return (size, sha256, fsops.file_identity(leaf)) if (size, sha256) in entry.expected else None
