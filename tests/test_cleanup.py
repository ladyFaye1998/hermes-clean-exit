from __future__ import annotations

import json
import os
import pytest

from clean_exit import fsops, paths, review
from clean_exit.errors import CleanExitError
from clean_exit.ledger import Ledger
from clean_exit.service import CleanExit
from clean_exit.tracking import WriteTracker


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    ledger = Ledger(tmp_path / "clean-exit.sqlite3")
    tracker = WriteTracker()
    registered = paths.register_folder(str(folder), paths.FolderPolicy())
    run = ledger.start_run(registered, session_id=None)
    return folder, ledger, tracker, run


def successful_write(ledger, tracker, file, content, *, session="main", call=None):
    """Exercise pre/post correlation around an actual filesystem write."""
    call = call or f"write-{file.name}"
    args = {"path": file.as_posix(), "content": content}
    tracker.before_write(ledger, args, session, call)
    file.write_bytes(content.encode("utf-8"))
    result = json.dumps({"resolved_path": str(file), "files_modified": [str(file)]})
    tracker.after_write(ledger, args, result, "ok", session, call)


def state(ledger, run, record):
    fresh = ledger.file_at(run.id, record.parts)
    assert fresh is not None
    return review.file_state(run, fresh, fsops.folder_problem(run.folder, run.folder_dev, run.folder_ino))


@pytest.mark.skipif(os.name != "nt", reason="exercise the Windows rename path")
def test_selected_archive_and_restore_preserve_bytes_and_identity(project):
    folder, ledger, tracker, run = project
    original = folder / "client-notes.md"
    original.write_bytes(b"Original input\n")
    brief = folder / "weekly-brief.md"
    outline = folder / "drafts" / "outline.md"
    outline.parent.mkdir()
    excerpts = folder / "excerpts.md"
    successful_write(ledger, tracker, brief, "Final brief\n")
    successful_write(ledger, tracker, outline, "Scratch outline\n")
    successful_write(ledger, tracker, excerpts, "Scratch excerpts\n")
    run = ledger.finish_run(run.id)
    records = {item.rel_path: item for item in ledger.files(run.id)}
    selected = [records["drafts/outline.md"], records["excerpts.md"]]
    identity = outline.stat().st_ino
    assert not (folder / ".clean-exit").exists()

    review.archive(ledger, run, selected)

    archived_outline = folder / ".clean-exit" / run.id / "drafts" / "outline.md"
    archived_excerpts = folder / ".clean-exit" / run.id / "excerpts.md"
    assert not outline.exists()
    assert not excerpts.exists()
    assert archived_outline.read_bytes() == b"Scratch outline\n"
    assert archived_outline.stat().st_ino == identity
    assert brief.read_bytes() == b"Final brief\n"
    assert original.read_bytes() == b"Original input\n"
    assert [state(ledger, run, item) for item in selected] == ["archived", "archived"]

    reopened = Ledger(ledger.path)
    archived = reopened.file_at(run.id, ("drafts", "outline.md"))
    assert archived.archive_rel == f".clean-exit/{run.id}/drafts/outline.md"
    review.restore(reopened.run(run.id), [archived])

    assert outline.read_bytes() == b"Scratch outline\n"
    assert outline.stat().st_ino == identity
    assert not archived_outline.exists()
    assert archived_excerpts.read_bytes() == b"Scratch excerpts\n"
    assert [state(reopened, run, item) for item in selected] == ["present", "archived"]


def test_existing_edits_and_other_sessions_are_not_claimed(project):
    folder, ledger, tracker, run = project
    original = folder / "client-notes.md"
    original.write_bytes(b"Pre-existing notes")
    successful_write(ledger, tracker, original, "Edited old notes", session="other")
    assert ledger.tracking_run().session_id is None
    assert ledger.files(run.id) == []

    successful_write(ledger, tracker, folder / "outline.md", "New notes", session="main")
    successful_write(ledger, tracker, folder / "unrelated.md", "Unrelated file", session="other")

    assert ledger.tracking_run().session_id == "main"
    assert [record.rel_path for record in ledger.files(run.id)] == ["outline.md"]
    assert original.read_bytes() == b"Edited old notes"
    assert (folder / "unrelated.md").read_bytes() == b"Unrelated file"


@pytest.mark.parametrize("failure", ["missing_id", "wrong_path", "wrong_content", "failed_status"])
def test_unverified_write_does_not_bind_or_record(project, failure):
    folder, ledger, tracker, run = project
    target = folder / "draft.md"
    args = {"path": str(target), "content": "draft"}
    tracker.before_write(ledger, args, "main", "call")
    target.write_bytes(b"other" if failure == "wrong_content" else b"draft")
    reported = str(folder / "different.md" if failure == "wrong_path" else target)
    result = {"resolved_path": reported, "files_modified": [reported]}
    status = "error" if failure == "failed_status" else "ok"
    call = None if failure == "missing_id" else "call"
    tracker.after_write(ledger, args, result, status, "main", call)

    assert ledger.tracking_run().session_id is None
    assert ledger.files(run.id) == []


def test_changed_file_refuses_entire_archive_selection(project):
    folder, ledger, tracker, run = project
    untouched = folder / "first.md"
    changed = folder / "second.md"
    successful_write(ledger, tracker, untouched, "first")
    successful_write(ledger, tracker, changed, "draft")
    run = ledger.finish_run(run.id)
    records = ledger.files(run.id)
    changed.write_bytes(b"other")  # Same size, different digest.

    assert state(ledger, run, records[1]) == "changed"
    with pytest.raises(CleanExitError, match="has changed"):
        review.archive(ledger, run, records)

    assert untouched.read_bytes() == b"first"
    assert changed.read_bytes() == b"other"
    assert not (folder / ".clean-exit").exists()


def test_missing_record_is_not_archived(project):
    folder, ledger, tracker, run = project
    target = folder / "draft.md"
    successful_write(ledger, tracker, target, "Draft")
    run = ledger.finish_run(run.id)
    record, = ledger.files(run.id)
    target.rename(folder / "moved-by-user.md")

    assert state(ledger, run, record) == "missing"
    with pytest.raises(CleanExitError, match="no longer there"):
        review.archive(ledger, run, [record])
    assert (folder / "moved-by-user.md").read_bytes() == b"Draft"


def test_same_bytes_at_a_new_file_identity_cannot_be_archived(project):
    folder, ledger, tracker, run = project
    target = folder / "draft.md"
    successful_write(ledger, tracker, target, "Same bytes")
    run = ledger.finish_run(run.id)
    record, = ledger.files(run.id)
    displaced = folder / "original-file.md"
    target.rename(displaced)
    target.write_bytes(displaced.read_bytes())

    assert target.stat().st_ino != displaced.stat().st_ino
    assert state(ledger, run, record) == "changed"
    with pytest.raises(CleanExitError, match="has changed"):
        review.archive(ledger, run, [record])
    assert target.read_bytes() == displaced.read_bytes() == b"Same bytes"
    assert not (folder / ".clean-exit").exists()


@pytest.mark.skipif(os.name != "nt", reason="exercise the Windows rename path")
def test_restore_conflict_preserves_archive_and_occupied_path(project):
    folder, ledger, tracker, run = project
    target = folder / "outline.md"
    successful_write(ledger, tracker, target, "Recorded draft")
    run = ledger.finish_run(run.id)
    record, = ledger.files(run.id)
    review.archive(ledger, run, [record])
    archived, = ledger.files(run.id)
    archive_file = folder.joinpath(*archived.archive_parts)
    target.write_bytes(b"New user file")

    assert state(ledger, run, archived) == "conflict"
    with pytest.raises(CleanExitError, match="something else"):
        review.restore(run, [archived])

    assert target.read_bytes() == b"New user file"
    assert archive_file.read_bytes() == b"Recorded draft"


@pytest.mark.skipif(os.name != "nt", reason="exercise the Windows rename path")
def test_windows_rename_refuses_to_replace_a_destination(tmp_path):
    source = tmp_path / "source.md"
    destination = tmp_path / "destination.md"
    source.write_bytes(b"source")
    destination.write_bytes(b"destination")

    with pytest.raises(OSError):
        fsops.move_no_replace(str(source), str(destination))

    assert source.read_bytes() == b"source"
    assert destination.read_bytes() == b"destination"


def test_service_requires_finish_before_archive_and_returns_relative_paths(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    service = CleanExit(Ledger(tmp_path / "ledger.sqlite3"), paths.FolderPolicy())
    assert service.status() == {"runs": []}
    active, = service.start({"folder": str(folder), "sessionId": "client-session"})["runs"]
    run_id = active["id"]
    assert active["status"] == "tracking"

    target = folder / "outline.md"
    args = {"path": str(target), "content": "Working notes"}
    service.before_write(args, "client-session", "write-outline")
    target.write_bytes(b"Working notes")
    result = {"resolved_path": str(target), "files_modified": [str(target)]}
    service.after_write(args, result, "ok", "client-session", "write-outline")
    recorded, = service.status()["runs"][0]["files"]
    assert recorded["path"] == "outline.md"
    assert recorded["state"] == "present"

    with pytest.raises(CleanExitError):
        service.archive({"runId": run_id, "fileIds": [recorded["id"]]})
    assert target.read_bytes() == b"Working notes"
    assert not (folder / ".clean-exit").exists()

    reviewed, = service.finish({"runId": run_id})["runs"]
    assert reviewed["status"] == "review"
    assert reviewed["files"] == [recorded]
