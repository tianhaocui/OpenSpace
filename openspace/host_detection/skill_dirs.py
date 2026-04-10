"""Auto-detect agent skill directories and broadcast evolved skills.

Scans well-known agent paths (Claude Code, Codex, Kiro, Hermes, Cursor)
plus the ``~/.agents/skills/`` shared hub.  Evolved skills (DERIVED /
CAPTURED) are broadcast to the shared hub with symlinks in each agent dir.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Optional

from openspace.utils.logging import Logger

logger = Logger.get_logger(__name__)

_SHARED_HUB = Path.home() / ".agents" / "skills"

# (agent_name, global_path, project_subpath, writable)
# Cursor uses .mdc format — discover for reading but skip on broadcast.
_AGENT_DIRS = [
    ("shared-hub", _SHARED_HUB,                          ".agents/skills",  True),
    ("claude",     Path.home() / ".claude" / "skills",    ".claude/skills",  True),
    ("codex",      Path.home() / ".codex" / "skills",     ".codex/skills",   True),
    ("kiro",       Path.home() / ".kiro" / "skills",      ".kiro/skills",    True),
    ("hermes",     Path.home() / ".hermes" / "skills",    None,              True),
    ("cursor",     Path.home() / ".cursor" / "rules",     ".cursor/rules",   False),
]

_AUTO_DETECT_ENV = "OPENSPACE_AUTO_DETECT"


def auto_detect_skill_dirs() -> List[Path]:
    """Scan well-known agent paths and return existing skill directories.

    Returns directories in priority order: shared hub first, then each
    agent's global dir, then project-level dirs.  Duplicates (same
    resolved path) are removed.

    Disabled when ``OPENSPACE_AUTO_DETECT=false``.
    """
    if os.environ.get(_AUTO_DETECT_ENV, "true").lower() == "false":
        return []

    seen: set[Path] = set()
    result: List[Path] = []
    cwd = Path.cwd()

    for name, global_path, project_sub, _writable in _AGENT_DIRS:
        for candidate in [global_path, cwd / project_sub if project_sub else None]:
            if candidate is None:
                continue
            if not candidate.exists():
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            result.append(candidate)
            logger.info(f"Auto-detected skill dir ({name}): {candidate}")

    return result


def _writable_agent_dirs() -> List[Path]:
    """Return existing agent skill directories that support SKILL.md format."""
    dirs: List[Path] = []
    for _name, global_path, _project_sub, writable in _AGENT_DIRS:
        if writable and global_path.exists() and global_path != _SHARED_HUB:
            dirs.append(global_path)
    return dirs


def broadcast_evolved_skill(
    skill_dir: Path,
    skill_name: str,
) -> int:
    """Copy skill to ~/.agents/skills/ and symlink from other agent dirs.

    Returns number of agent directories that received a new symlink.
    Skips if ~/.agents/skills/ doesn't exist (user hasn't opted in).
    """
    if not _SHARED_HUB.exists():
        logger.debug("Shared hub %s not found, skipping broadcast", _SHARED_HUB)
        return 0

    hub_target = _SHARED_HUB / skill_name

    # Copy to shared hub (atomic: tmp dir + rename)
    if not hub_target.exists():
        tmp = _SHARED_HUB / f".{skill_name}.tmp"
        try:
            if tmp.exists():
                shutil.rmtree(tmp)
            shutil.copytree(skill_dir, tmp)
            tmp.rename(hub_target)
            logger.info(f"Broadcast: copied {skill_name} to {hub_target}")
        except OSError as e:
            logger.warning(f"Broadcast: failed to copy to shared hub: {e}")
            return 0

    # Create symlinks in writable agent dirs
    linked = 0
    for agent_dir in _writable_agent_dirs():
        link_path = agent_dir / skill_name
        if link_path.exists() or link_path.is_symlink():
            continue
        try:
            link_path.symlink_to(hub_target)
            linked += 1
            logger.info(f"Broadcast: symlinked {link_path} -> {hub_target}")
        except OSError as e:
            logger.warning(f"Broadcast: symlink failed for {link_path}: {e}")

    return linked
