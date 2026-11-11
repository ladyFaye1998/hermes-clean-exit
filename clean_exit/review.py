"""Review: derive each recorded file's state from disk, archive on request, restore on request.

A file's state is never stored. It is computed from what is at its original location and at its
archive location, so a crash between "plan" and "move", or a retried request, reads back as
whatever is true on disk. Each file moves with one no-overwrite rename; a batch is a sequence of
such moves, not a transaction.
"""
from __future__ import annotations

import os
from typing import Callable, Optional, Sequence

from . import fsops, paths
from .errors import CleanExitError
from .fsops import ABSENT, CHANGED, MATCH
from .ledger import FileRecord, Ledger, Run

PRESENT = "present"
ARCHIVED = "archived"
CHANGED_STATE = "changed"
MISSING = "missing"
CONFLICT = "conflict"

# (original location, archive location) -> state. Any pairing not listed is a conflict.
_STATES = {
    (MATCH, ABSENT): PRESENT,
    (ABSENT, MATCH): ARCHIVED,
    (ABSENT, ABSENT): MISSING,
    (CHANGED, ABSENT): CHANGED_STATE,
    (ABSENT, CHANGED): CHANGED_STATE,
}
_WHY_NOT = {
    PRESENT: "is not archived",
    ARCHIVED: "is already archived",
    CHANGED_STATE: "has changed since it was recorded",
    MISSING: "is no longer there",
    CONFLICT: "is linked, blocked, or has something else at its original or archive location",
}


def archive_location(run: Run, record: FileRecord) -> tuple[str, ...]:
    return record.archive_parts or paths.archive_parts(run.id, record.parts)


def file_state(run: Run, record: FileRecord, folder_problem: Optional[str]) -> str:
    """One of present, archived, changed, missing, conflict."""
    if folder_problem:
        return MISSING if folder_problem == "missing" else CONFLICT
    original = fsops.probe(run.folder, record.parts, record.size, record.sha256, record.identity)
    archived = fsops.probe(run.folder, archive_location(run, record), record.size, record.sha256, record.identity)
    if record.archive_rel is None and archived != ABSENT:
        return CONFLICT  # something occupies an archive location this plugin never planned to use
    return _STATES.get((original, archived), CONFLICT)


def _require_folder(run: Run) -> None:
    problem = fsops.folder_problem(run.folder, run.folder_dev, run.folder_ino)
    if problem == "missing":
        raise CleanExitError(f"The tracked folder {run.folder} is missing. Nothing was moved.")
    if problem:
        raise CleanExitError(f"The tracked folder {run.folder} was replaced or relinked after tracking "
                             "started. Nothing was moved.")


def _validate(run: Run, records: Sequence[FileRecord], required: str,
              too_long: Callable[[FileRecord], bool]) -> None:
    """Check the whole request before the first move; refuse it entirely on any problem."""
    _require_folder(run)
    refusals = []
    for record in records:
        state = file_state(run, record, None)
        if state != required:
            refusals.append(f"{paths.display_path(record.parts)} {_WHY_NOT[state]}")
        elif too_long(record):
            refusals.append(f"{paths.display_path(record.parts)} would have a path that is too long")
    if refusals:
        raise CleanExitError("Nothing was moved: " + "; ".join(refusals) + ".")


def _move_each(run: Run, records: Sequence[FileRecord], source_of: Callable[[FileRecord], tuple[str, ...]],
               destination_of: Callable[[FileRecord], tuple[str, ...]], verb: str) -> None:
    for done, record in enumerate(records):
        source, destination = source_of(record), destination_of(record)
        try:
            if fsops.folder_problem(run.folder, run.folder_dev, run.folder_ino):
                raise fsops.UnsafePath("the tracked folder changed while the request was running")
            fsops.ensure_dirs(run.folder, destination[:-1])
            # Re-check immediately before the rename: only the recorded bytes move, only to a free slot.
            if fsops.probe(run.folder, source, record.size, record.sha256, record.identity) != MATCH:
                raise fsops.UnsafePath("it changed while the request was running")
            if fsops.walk(run.folder, destination) is not None:
                raise fsops.UnsafePath("its destination became occupied")
            if fsops.folder_problem(run.folder, run.folder_dev, run.folder_ino):
                raise fsops.UnsafePath("the tracked folder changed while the request was running")
            fsops.move_no_replace(os.path.join(run.folder, *source), os.path.join(run.folder, *destination))
        except (OSError, fsops.UnsafePath) as exc:
            reason = getattr(exc, "strerror", None) or str(exc)
            raise CleanExitError(
                f"{verb} {done} of {len(records)} files, then stopped at {paths.display_path(record.parts)}: "
                f"{reason}. Files move one at a time. Refresh to see where each file is.") from exc


def archive(ledger: Ledger, run: Run, records: Sequence[FileRecord]) -> None:
    """Move each selected file to ``.clean-exit/<run id>/<relative path>`` inside the folder."""
    destinations = {record.id: paths.archive_parts(run.id, record.parts) for record in records}
    _validate(run, records, PRESENT, lambda record: paths.too_long(run.folder, destinations[record.id]))
    # The destination is committed to the ledger before anything moves. If the process dies after
    # this line, each file is still exactly at its original or its planned archive location.
    ledger.plan_archive(run.id, {file_id: paths.rel_path(parts) for file_id, parts in destinations.items()})
    _move_each(run, records, lambda record: record.parts, lambda record: destinations[record.id], "Archived")


def restore(run: Run, records: Sequence[FileRecord]) -> None:
    """Move each selected archived file back to its original location, never onto another file."""
    _validate(run, records, ARCHIVED, lambda record: paths.too_long(run.folder, record.parts))
    _move_each(run, records, lambda record: archive_location(run, record), lambda record: record.parts,
               "Restored")
