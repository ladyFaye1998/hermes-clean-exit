"""Filesystem primitives. Everything that touches the user's folder goes through this module.

The only mutations here are creating a directory and renaming one file without replacing
anything. There is no delete, no copy and no overwrite.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import stat
import sys
from typing import Optional, Sequence

IS_WINDOWS = os.name == "nt"

# What a recorded file looks like at one location, compared with its ledger entry.
ABSENT = "absent"      # nothing there
MATCH = "match"        # a plain, unlinked regular file with the recorded size and digest
CHANGED = "changed"    # a plain, unlinked regular file with other content
CONFLICT = "conflict"  # linked, a reparse point, not a regular file, or unreadable


class UnsafePath(Exception):
    """A path component is a link/reparse point or is not what it has to be."""


def is_reparse(st: os.stat_result) -> bool:
    """True for symlinks, junctions and every other reparse point."""
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def is_plain_dir(st: os.stat_result) -> bool:
    return stat.S_ISDIR(st.st_mode) and not is_reparse(st)


def is_plain_file(st: os.stat_result) -> bool:
    return stat.S_ISREG(st.st_mode) and not is_reparse(st)


def walk(root: str, parts: Sequence[str]) -> Optional[os.stat_result]:
    """lstat every component from ``root`` down to the leaf, never following a link.

    Returns the leaf's lstat, or None when the leaf (or one of its parents) does not exist.
    Raises UnsafePath when an existing component is a reparse point or a parent is not a directory.
    """
    if not is_plain_dir(os.lstat(root)):
        raise UnsafePath(f"{root} is not a plain folder")
    current = root
    st: Optional[os.stat_result] = None
    for index, part in enumerate(parts):
        current = os.path.join(current, part)
        try:
            st = os.lstat(current)
        except (FileNotFoundError, NotADirectoryError):
            return None
        if is_reparse(st):
            raise UnsafePath(f"{current} is a link or reparse point")
        if index < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
            raise UnsafePath(f"{current} is not a folder")
    return st


def file_identity(st: os.stat_result) -> tuple[str, str]:
    return str(st.st_dev), str(st.st_ino)


def _same_file(a: os.stat_result, b: os.stat_result) -> bool:
    return (is_plain_file(b) and b.st_nlink == 1 and file_identity(a) == file_identity(b)
            and a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns)


def sha256_file(path: str, before: os.stat_result) -> tuple[str, int]:
    """Hash the observed file, refusing replacements and growth while reading."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        if not _same_file(before, os.fstat(handle.fileno())):
            raise UnsafePath("The file changed before it could be verified")
        while chunk := handle.read(min(1024 * 1024, before.st_size - size + 1)):
            digest.update(chunk)
            size += len(chunk)
            if size > before.st_size:
                raise UnsafePath("The file grew while it was being verified")
        if not _same_file(before, os.fstat(handle.fileno())) or not _same_file(before, os.lstat(path)):
            raise UnsafePath("The file changed while it was being verified")
    return digest.hexdigest(), size


def probe(root: str, parts: Sequence[str], size: int, sha256: str,
          identity: Optional[tuple[str, str]] = None) -> str:
    """Compare what is at ``root/parts`` with the recorded file."""
    try:
        st = walk(root, parts)
    except (UnsafePath, OSError):
        return CONFLICT
    if st is None:
        return ABSENT
    if not is_plain_file(st) or st.st_nlink > 1:
        return CONFLICT
    if st.st_size != size or (identity is not None and file_identity(st) != identity):
        return CHANGED
    try:
        actual, read = sha256_file(os.path.join(root, *parts), st)
    except (UnsafePath, OSError):
        return CONFLICT
    return MATCH if (actual, read) == (sha256, size) else CHANGED


def folder_problem(folder: str, dev: str, ino: str) -> Optional[str]:
    """Why the selected folder can no longer be trusted: 'missing', 'replaced', or None when it is
    still the same plain directory that was registered."""
    try:
        st = os.lstat(folder)
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except OSError:
        return "replaced"
    if not is_plain_dir(st) or (str(st.st_dev), str(st.st_ino)) != (dev, ino):
        return "replaced"
    try:
        real = os.path.realpath(folder)
    except OSError:
        return "replaced"
    return None if os.path.normcase(real) == os.path.normcase(folder) else "replaced"


def ensure_dirs(root: str, parts: Sequence[str]) -> None:
    """Create ``root/parts`` one level at a time; every level must end up a plain directory."""
    current = root
    for part in parts:
        current = os.path.join(current, part)
        try:
            os.mkdir(current)
        except FileExistsError:
            pass
        if not is_plain_dir(os.lstat(current)):
            raise UnsafePath(f"{current} is not a plain folder")


def is_local_drive(anchor: str) -> bool:
    """True when a Windows drive root is a fixed, removable or RAM disk (not network or CD-ROM)."""
    if not IS_WINDOWS:
        return True
    return _kernel32().GetDriveTypeW(anchor) in (2, 3, 6)


def _kernel32():
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
    kernel32.MoveFileExW.restype = wintypes.BOOL
    kernel32.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
    kernel32.GetDriveTypeW.restype = wintypes.UINT
    return kernel32


def _renameat2():
    """Linux ``renameat2`` (used with RENAME_NOREPLACE), or None when libc does not export it."""
    try:
        function = ctypes.CDLL(None, use_errno=True).renameat2
    except (OSError, AttributeError):
        return None
    function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    function.restype = ctypes.c_int
    return function


def move_no_replace(source: str, destination: str) -> None:
    """Rename ``source`` to ``destination`` on the same volume, failing if the destination exists.

    Windows: ``MoveFileExW`` with no flags, which neither replaces an existing file nor falls back
    to copy+delete across volumes. Linux: ``renameat2(RENAME_NOREPLACE)``. Any other platform is
    refused because a plain POSIX rename silently overwrites.
    """
    if IS_WINDOWS:
        if not _kernel32().MoveFileExW(source, destination, 0):
            code = ctypes.get_last_error()
            raise ctypes.WinError(code, f"could not move {source} to {destination}")
        return
    rename = _renameat2() if sys.platform.startswith("linux") else None
    if rename is None:
        raise OSError(errno.ENOTSUP, "this platform has no rename that refuses to overwrite")
    at_fdcwd, rename_noreplace = -100, 1
    if rename(at_fdcwd, os.fsencode(source), at_fdcwd, os.fsencode(destination), rename_noreplace) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), source, None, destination)
