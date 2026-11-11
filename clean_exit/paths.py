"""Path rules: which folder may be registered and which written paths may be recorded.

Paths are handled as (anchor, parts). Every later filesystem access is built from the registered
folder plus validated relative parts, never from a path string a tool supplied.
"""
from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import fsops
from .errors import CleanExitError

ARCHIVE_DIR = ".clean-exit"
MAX_WINDOWS_PATH = 259

# Directory or file names that are never recorded and never registered, wherever they appear.
_EXCLUDED_NAMES = frozenset({
    ".git", ARCHIVE_DIR, ".hermes", ".ssh", ".aws", ".azure", ".gnupg", ".kube", ".docker",
})
# File names that commonly hold credentials. Matched against each lower-cased path component.
_SENSITIVE_PATTERNS = (
    ".env", ".env.*", "*.env", ".netrc", "_netrc", ".npmrc", ".pypirc", ".git-credentials", ".htpasswd",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "*.pem", "*.key", "*.pfx", "*.p12", "*.jks",
    "*.keystore", "*.kdbx", "*.ppk", "credentials", "credentials.*", "secret.*", "secrets.*",
    "auth.json", "token.json", "state.db", "config.yaml", "config.yml",
)
_WINDOWS_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')
_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|conin\$|conout\$|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)
_WINDOWS_DRIVE = re.compile(r"^([A-Za-z]):[\\/]")


def fold(text: str) -> str:
    """Comparison form of a path component (case-insensitive on Windows)."""
    return os.path.normcase(text)


def _valid_part(part: str) -> bool:
    if part in ("", ".", ".."):
        return False
    if fsops.IS_WINDOWS:
        return not (_WINDOWS_ILLEGAL.search(part) or part[-1] in ". " or _WINDOWS_RESERVED.match(part))
    return "\x00" not in part


def split_absolute(path: object) -> Optional[tuple[str, tuple[str, ...]]]:
    """Split an absolute local path into (anchor, parts), or None when it is anything else:
    relative, UNC or device paths, ``.``/``..`` segments, empty segments, stream or device names."""
    if not isinstance(path, str) or not path or "\x00" in path:
        return None
    if fsops.IS_WINDOWS:
        drive = _WINDOWS_DRIVE.match(path)
        if not drive:
            return None
        anchor, rest, separators = drive.group(1).upper() + ":\\", path[3:], r"[\\/]"
    else:
        if not path.startswith("/") or path.startswith("//"):
            return None
        anchor, rest, separators = "/", path[1:], "/"
    parts = tuple(re.split(separators, rest)) if rest else ()
    return (anchor, parts) if all(_valid_part(part) for part in parts) else None


def is_excluded(parts: Iterable[str]) -> bool:
    """True when any component is a VCS/archive/credential directory or a credential-style file."""
    for part in parts:
        name = part.lower()
        if fold(part) in _EXCLUDED_NAMES or name in _EXCLUDED_NAMES:
            return True
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in _SENSITIVE_PATTERNS):
            return True
    return False


def tracked_parts(folder: str, path: object) -> Optional[tuple[str, ...]]:
    """Relative parts of ``path`` under ``folder`` when it may be recorded, else None."""
    root, target = split_absolute(folder), split_absolute(path)
    if root is None or target is None:
        return None
    (root_anchor, root_parts), (anchor, parts) = root, target
    if fold(anchor) != fold(root_anchor) or len(parts) <= len(root_parts):
        return None
    if any(fold(a) != fold(b) for a, b in zip(root_parts, parts)):
        return None
    relative = parts[len(root_parts):]
    return None if is_excluded(relative) else relative


def rel_path(parts: Iterable[str]) -> str:
    """Ledger form of relative parts."""
    return "/".join(parts)


def rel_key(parts: Iterable[str]) -> str:
    """Uniqueness key of relative parts within a run."""
    return "/".join(fold(part) for part in parts)


def display_path(parts: Iterable[str]) -> str:
    """Relative path as the card shows it."""
    return os.sep.join(parts)


def archive_parts(run_id: str, parts: Iterable[str]) -> tuple[str, ...]:
    """Where a recorded file goes when archived: ``.clean-exit/<run id>/<its relative path>``."""
    return (ARCHIVE_DIR, run_id, *parts)


def too_long(folder: str, parts: Iterable[str]) -> bool:
    return fsops.IS_WINDOWS and len(os.path.join(folder, *parts)) > MAX_WINDOWS_PATH


def _contains(parent: str, child: str) -> bool:
    """True when ``child`` is ``parent`` or lies inside it."""
    a, b = split_absolute(parent), split_absolute(child)
    if a is None or b is None:
        return False
    (pa, pp), (ca, cp) = a, b
    return fold(pa) == fold(ca) and len(cp) >= len(pp) and all(fold(x) == fold(y) for x, y in zip(pp, cp))


@dataclass(frozen=True)
class FolderPolicy:
    """Locations a tracked folder must stay clear of.

    ``protected_trees``: the folder may not be one, be inside one, or contain one.
    ``protected_folders``: the folder may not be one or contain one (inside is fine: a project
    under the user's profile folder is the normal case).
    """
    protected_trees: tuple[str, ...] = ()
    protected_folders: tuple[str, ...] = ()

    def refusal(self, folder: str) -> Optional[str]:
        for tree in self.protected_trees:
            if _contains(tree, folder):
                return "That folder is a system or Hermes data location. Choose a project folder."
        for location in (*self.protected_trees, *self.protected_folders):
            if _contains(folder, location):
                return "That folder contains system, profile or Hermes data. Choose a project folder inside it."
        return None

    def also_protecting(self, *trees: str) -> "FolderPolicy":
        return FolderPolicy((*self.protected_trees, *_normalized(trees)), self.protected_folders)


def _normalized(candidates: Iterable[object]) -> tuple[str, ...]:
    """Absolute forms of the given locations, plus their link-resolved forms when different."""
    result: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        absolute = os.path.abspath(str(candidate))
        for form in (absolute, os.path.realpath(absolute)):
            if split_absolute(form) is not None and form not in result:
                result.append(form)
    return tuple(result)


def default_policy(hermes_home: Optional[Path] = None, environ: Optional[Mapping[str, str]] = None,
                   home: Optional[Path] = None) -> FolderPolicy:
    """Protected locations for this machine: OS directories, application data, the user profile
    folder itself, and the Hermes home of the active profile (plus the shared Hermes root when the
    home is a named profile)."""
    env = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    hermes: list[object] = []
    if hermes_home is not None:
        hermes.append(hermes_home)
        if hermes_home.parent.name.lower() == "profiles":
            hermes.append(hermes_home.parent.parent)
    if fsops.IS_WINDOWS:
        trees = [env.get(name) for name in (
            "SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData",
            "APPDATA", "LOCALAPPDATA")]
        trees.append(home / "AppData")
        folders = [home, env.get("USERPROFILE"), env.get("PUBLIC")]
    else:
        trees = ["/bin", "/boot", "/dev", "/etc", "/lib", "/proc", "/sbin", "/sys", "/usr"]
        folders = [home]
    return FolderPolicy(_normalized([*trees, *hermes]), _normalized(folders))


@dataclass(frozen=True)
class RegisteredFolder:
    path: str
    dev: str
    ino: str


def register_folder(folder: object, policy: FolderPolicy) -> RegisteredFolder:
    """Validate the folder the user picked and return its canonical path and identity."""
    if not isinstance(folder, str) or not folder.strip():
        raise CleanExitError("Choose a folder to track.")
    split = split_absolute(folder) or split_absolute(folder.rstrip("\\/" if fsops.IS_WINDOWS else "/"))
    if split is None:
        raise CleanExitError("Choose a folder on a local drive by its full path.")
    anchor, parts = split
    if not parts:
        raise CleanExitError("A whole drive cannot be tracked. Choose a project folder.")
    if not fsops.is_local_drive(anchor):
        raise CleanExitError("Only folders on a local drive can be tracked.")
    if is_excluded(parts):
        raise CleanExitError("That folder is inside a version-control, archive or credentials folder.")
    try:
        leaf = fsops.walk(anchor, parts)
    except fsops.UnsafePath:
        raise CleanExitError("That folder is, or is reached through, a link or junction. Choose the real folder.")
    except OSError as exc:
        raise CleanExitError(f"That folder cannot be read: {exc.strerror or exc}.")
    if leaf is None:
        raise CleanExitError("That folder does not exist.")
    if not fsops.is_plain_dir(leaf):
        raise CleanExitError("That is not a folder.")
    path = os.path.join(anchor, *parts)
    real = os.path.realpath(path)
    if fold(real) != fold(path):
        raise CleanExitError("That folder is reached through a link or substituted drive. Choose the real folder.")
    if too_long(real, (ARCHIVE_DIR, "0" * 16, "x")):
        raise CleanExitError("That folder's path is too long to hold an archive.")
    refusal = policy.refusal(real)
    if refusal:
        raise CleanExitError(refusal)
    identity = os.lstat(real)
    return RegisteredFolder(real, str(identity.st_dev), str(identity.st_ino))
