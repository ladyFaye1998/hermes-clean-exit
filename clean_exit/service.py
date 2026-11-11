"""The Clean Exit run lifecycle, independent of Hermes and Desktop."""
from __future__ import annotations

import os
import threading
from typing import Any

from . import fsops, paths, review
from .errors import CleanExitError
from .ledger import REVIEW, ActiveRunExists, FileRecord, Ledger, Run
from .tracking import WriteTracker


class CleanExit:
    def __init__(self, ledger: Ledger, policy: paths.FolderPolicy, tracker: WriteTracker | None = None):
        self.ledger = ledger
        self.policy = policy
        self.tracker = tracker if tracker is not None else WriteTracker()
        self._actions = threading.RLock()

    def status(self, params: dict | None = None) -> dict:
        with self._actions:
            return {"runs": [self._public_run(run) for run in self.ledger.runs()]}

    def start(self, params: dict) -> dict:
        params = self._params(params)
        session_id = params.get("sessionId")
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
            raise CleanExitError("Choose a valid session or let the first matching write select one.")
        with self._actions:
            if self.ledger.tracking_run() is not None:
                raise CleanExitError("Finish the current tracking run before starting another.")
            folder = paths.register_folder(params.get("folder"), self.policy)
            try:
                self.ledger.start_run(folder, session_id)
            except ActiveRunExists as exc:
                raise CleanExitError("Finish the current tracking run before starting another.") from exc
            return self.status()

    def finish(self, params: dict) -> dict:
        with self._actions:
            run = self._find_run(self._params(params))
            self.ledger.finish_run(run.id)
            self.tracker.forget_run(run.id)
            return self.status()

    def archive(self, params: dict) -> dict:
        with self._actions:
            run, files = self._selection(params)
            review.archive(self.ledger, run, files)
            return self.status()

    def restore(self, params: dict) -> dict:
        with self._actions:
            run, files = self._selection(params)
            review.restore(run, files)
            return self.status()

    def before_write(self, args: Any, session_id: Any, tool_call_id: Any, turn_id: Any = None) -> None:
        self.tracker.before_write(self.ledger, args, session_id, tool_call_id, turn_id=turn_id)

    def after_write(self, args: Any, result: Any, status: Any, session_id: Any,
                    tool_call_id: Any, turn_id: Any = None) -> None:
        self.tracker.after_write(self.ledger, args, result, status, session_id, tool_call_id, turn_id=turn_id)

    @staticmethod
    def _params(params: Any) -> dict:
        if not isinstance(params, dict):
            raise CleanExitError("This request needs a parameter object.")
        return params

    def _find_run(self, params: dict) -> Run:
        run_id = params.get("runId")
        if not isinstance(run_id, str) or not run_id:
            raise CleanExitError("Choose a tracked run.")
        run = self.ledger.run(run_id)
        if run is None:
            raise CleanExitError("This run could not be found in the current profile.")
        return run

    def _selection(self, params: dict) -> tuple[Run, list[FileRecord]]:
        params = self._params(params)
        run = self._find_run(params)
        if run.status != REVIEW:
            raise CleanExitError("Finish tracking before moving files from this run.")
        file_ids = params.get("fileIds")
        if not isinstance(file_ids, list) or not file_ids:
            raise CleanExitError("Select one or more recorded files.")
        if any(not isinstance(file_id, str) or not file_id for file_id in file_ids):
            raise CleanExitError("One of the selected file IDs is invalid.")
        if len(set(file_ids)) != len(file_ids):
            raise CleanExitError("Each selected file must appear once.")
        recorded = {record.id: record for record in self.ledger.files(run.id)}
        if any(file_id not in recorded for file_id in file_ids):
            raise CleanExitError("A selected file does not belong to this run.")
        return run, [recorded[file_id] for file_id in file_ids]

    def _public_run(self, run: Run) -> dict:
        problem = fsops.folder_problem(run.folder, run.folder_dev, run.folder_ino)
        records = self.ledger.files(run.id)
        return {
            "id": run.id,
            "folder": run.folder,
            "folderName": os.path.basename(run.folder),
            "status": run.status,
            "sessionId": run.session_id,
            "files": [
                {
                    "id": record.id,
                    "path": paths.display_path(record.parts),
                    "size": record.size,
                    "state": review.file_state(run, record, problem),
                }
                for record in records
            ],
        }
