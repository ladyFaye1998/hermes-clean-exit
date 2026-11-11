"""Public Hermes hooks and Desktop RPCs for Clean Exit."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from . import fsops, paths
from .errors import CleanExitError
from .ledger import Ledger
from .service import CleanExit


PLUGIN_ID = "clean-exit"
logger = logging.getLogger(__name__)


def register(ctx) -> None:
    from plugins.plugin_storage import plugin_data_dir

    services: dict[Path, CleanExit] = {}
    services_lock = threading.Lock()

    def for_profile() -> CleanExit:
        # The gateway can serve multiple profiles in one process. Resolve the
        # active storage path inside each call, under Hermes's profile scope.
        directory = plugin_data_dir(PLUGIN_ID)
        with services_lock:
            service = services.get(directory)
            if service is None:
                policy = paths.default_policy(hermes_home=directory.parent.parent)
                service = CleanExit(Ledger(directory / "ledger.sqlite3"), policy)
                services[directory] = service
            return service

    def before_tool(tool_name, args, session_id=None, tool_call_id=None, turn_id=None, **kwargs):
        if tool_name != "write_file" or not fsops.IS_WINDOWS:
            return
        try:
            for_profile().before_write(args, session_id, tool_call_id, turn_id)
        except Exception:
            # A failed observation cannot establish file ownership. Leave the
            # write under Hermes's normal guards and omit it from this run.
            logger.debug("Clean Exit could not observe the start of a file write", exc_info=True)

    def after_tool(tool_name, args, result, status=None, session_id=None, tool_call_id=None,
                   turn_id=None, **kwargs):
        if tool_name != "write_file" or not fsops.IS_WINDOWS:
            return
        try:
            for_profile().after_write(args, result, status, session_id, tool_call_id, turn_id)
        except Exception:
            logger.debug("Clean Exit could not verify a completed file write", exc_info=True)

    def handler(name):
        def call(params, *, session_id=None, **kwargs):
            if not fsops.IS_WINDOWS:
                raise CleanExitError("Clean Exit runs on a local Windows Hermes profile.")
            return getattr(for_profile(), name)(params)
        return call

    ctx.register_hook("pre_tool_call", before_tool)
    ctx.register_hook("post_tool_call", after_tool)
    for name in ("status", "start", "finish", "archive", "restore"):
        ctx.register_rpc(name, handler(name))
