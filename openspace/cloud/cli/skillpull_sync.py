"""Bidirectional sync between OpenSpace skills and Git repos via skillpull.

Pull:  skillpull pull --path <host_skill_dir> → register into SkillRegistry + SkillStore
Push:  export evolved skills to host skill dir → skillpull push → Git repo

OpenSpace runs as an MCP server behind a host agent (Claude Code, Codex,
Kiro, etc.).  The host agent's skill directory is passed via the
``OPENSPACE_HOST_SKILL_DIRS`` environment variable.  This module uses that
directory directly — no separate ``.openspace/skills`` needed.

Requires the ``skillpull`` CLI to be installed and on PATH.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import os

from openspace.utils.logging import Logger

logger = Logger.get_logger(__name__)

SIDECAR_FILES = {".skill_id", ".upload_meta.json"}
SKILLPULL_MANIFEST = ".skillpull.json"
_HOST_SKILL_DIRS_ENV = "OPENSPACE_HOST_SKILL_DIRS"


@dataclass
class SkillpullResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def find_skillpull() -> str:
    """Locate the skillpull binary. Raises FileNotFoundError if not found."""
    import shutil as _shutil

    path = _shutil.which("skillpull")
    if path:
        return path

    # Common install locations
    for candidate in [
        Path.home() / ".local" / "bin" / "skillpull",
        Path("/root/skillpull/skillpull"),
    ]:
        if candidate.exists() and candidate.stat().st_mode & 0o111:
            return str(candidate)

    raise FileNotFoundError(
        "skillpull not found. Install via: npm i -g skillpull"
    )


def get_target_dir() -> Path:
    """Return the skill directory to use for skillpull operations.

    Resolution order:
      1. First directory from ``OPENSPACE_HOST_SKILL_DIRS`` (set by host agent)
      2. ``~/.agents/skills/`` shared hub (if exists)
      3. Fallback: ``.openspace/skills`` in cwd (standalone / debug mode)
    """
    raw = os.environ.get(_HOST_SKILL_DIRS_ENV, "")
    if raw:
        first = raw.split(",")[0].strip()
        if first:
            p = Path(first)
            if p.exists():
                return p
            logger.warning(f"{_HOST_SKILL_DIRS_ENV} first dir does not exist: {first}")

    shared_hub = Path.home() / ".agents" / "skills"
    if shared_hub.exists():
        return shared_hub

    return Path.cwd() / ".openspace" / "skills"


async def run_skillpull(
    args: List[str],
    cwd: Optional[str] = None,
    timeout: float = 120.0,
) -> SkillpullResult:
    """Run skillpull as a subprocess with --path pointing to host skill dir."""
    binary = find_skillpull()
    target_dir = get_target_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    cmd = [binary, "--path", str(target_dir), "--quiet"] + args

    logger.info(f"Running: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return SkillpullResult(1, "", f"skillpull timed out after {timeout}s")

    return SkillpullResult(
        returncode=proc.returncode or 0,
        stdout=stdout.decode(errors="replace").strip(),
        stderr=stderr.decode(errors="replace").strip(),
    )


def _read_manifest(target_dir: Path) -> Dict[str, Any]:
    """Read .skillpull.json manifest from target directory."""
    manifest_path = target_dir / SKILLPULL_MANIFEST
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


async def pull_skills(
    repo: Optional[str] = None,
    skill_name: Optional[str] = None,
    force: bool = False,
    branch: Optional[str] = None,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Pull skills from a Git repo via skillpull into the host skill directory.

    Returns dict with target_dir, pulled skill names, and any errors.
    """
    args = ["pull"] if repo is None else ["pull", repo]
    if skill_name:
        args.append(skill_name)
    if force:
        args.append("--force")
    if branch:
        args.extend(["--branch", branch])
    if project:
        args.extend(["--project", project])

    result = await run_skillpull(args)
    target_dir = get_target_dir()

    if not result.ok:
        return {
            "success": False,
            "error": result.stderr or result.stdout,
            "target_dir": str(target_dir),
        }

    # Read manifest to find what was pulled
    manifest = _read_manifest(target_dir)
    skill_names = list(manifest.get("skills", {}).keys())

    return {
        "success": True,
        "target_dir": str(target_dir),
        "skills": skill_names,
        "count": len(skill_names),
    }


async def pull_and_register(
    registry,
    store,
    repo: Optional[str] = None,
    skill_name: Optional[str] = None,
    force: bool = False,
    branch: Optional[str] = None,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Pull skills from Git and register them into OpenSpace's registry + DB."""
    pull_result = await pull_skills(
        repo=repo, skill_name=skill_name, force=force,
        branch=branch, project=project,
    )
    if not pull_result["success"]:
        return pull_result

    target_dir = Path(pull_result["target_dir"])
    if not target_dir.exists():
        pull_result["registered"] = 0
        return pull_result

    added = registry.discover_from_dirs([target_dir])
    db_created = 0
    if added:
        db_created = await store.sync_from_registry(added)

    pull_result["registered"] = len(added)
    pull_result["db_created"] = db_created
    logger.info(
        f"skillpull pull: {len(added)} skill(s) registered, {db_created} new DB record(s)"
    )
    return pull_result


def export_evolved_for_push(
    store,
    skill_ids: Optional[List[str]] = None,
    target_dir: Optional[Path] = None,
) -> List[str]:
    """Copy evolved skills to the skillpull target dir, stripping sidecars.

    If skill_ids is None, exports all active evolved skills (FIXED/DERIVED/CAPTURED).
    Returns list of exported skill names.
    """
    if target_dir is None:
        target_dir = get_target_dir()

    records = store.load_all(active_only=True)

    # Filter to evolved skills
    from openspace.skill_engine.types import SkillOrigin
    evolved_origins = {SkillOrigin.FIXED, SkillOrigin.DERIVED, SkillOrigin.CAPTURED}

    to_export = {}
    for sid, rec in records.items():
        if rec.lineage.origin not in evolved_origins:
            continue
        if skill_ids and sid not in skill_ids:
            continue
        to_export[sid] = rec

    if not to_export:
        return []

    target_dir.mkdir(parents=True, exist_ok=True)
    exported = []

    for sid, rec in to_export.items():
        src = Path(rec.path).parent if rec.path else None
        if not src or not src.exists():
            logger.warning(f"Skill dir not found for {sid}: {src}")
            continue

        dst = target_dir / rec.name
        # Copy to temp dir first, then atomic rename to avoid data loss
        tmp_dst = target_dir / f".{rec.name}.tmp"
        if tmp_dst.exists():
            shutil.rmtree(tmp_dst)

        shutil.copytree(src, tmp_dst, ignore=shutil.ignore_patterns(*SIDECAR_FILES))

        if dst.exists():
            shutil.rmtree(dst)
        tmp_dst.rename(dst)

        exported.append(rec.name)
        logger.info(f"Exported evolved skill: {rec.name} -> {dst}")

    return exported


async def push_skills(
    repo: Optional[str] = None,
    store=None,
    skill_ids: Optional[List[str]] = None,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Export evolved skills and push to Git repo via skillpull."""
    exported = []
    if store:
        exported = export_evolved_for_push(store, skill_ids)
        if not exported:
            return {"success": False, "error": "No evolved skills to push"}

    args = ["push"]
    if repo:
        args.append(repo)
    if project:
        args.extend(["--project", project])

    result = await run_skillpull(args)

    if not result.ok:
        return {
            "success": False,
            "error": result.stderr or result.stdout,
            "exported": exported,
        }

    return {
        "success": True,
        "exported": exported,
        "count": len(exported),
    }


def main() -> None:
    """CLI entry point: openspace-skillpull."""
    parser = argparse.ArgumentParser(
        prog="openspace-skillpull",
        description="Sync skills between OpenSpace and Git repos via skillpull",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # pull
    p_pull = sub.add_parser("pull", help="Pull skills from Git repo")
    p_pull.add_argument("repo", nargs="?", help="Git repo URL, user/repo, or @alias")
    p_pull.add_argument("skill", nargs="?", help="Pull only this skill")
    p_pull.add_argument("--force", "-f", action="store_true")
    p_pull.add_argument("--branch", help="Git branch/tag")
    p_pull.add_argument("--project", help="Project scope")

    # push
    p_push = sub.add_parser("push", help="Push evolved skills to Git repo")
    p_push.add_argument("repo", nargs="?", help="Git repo URL, user/repo, or @alias")
    p_push.add_argument("--skill-ids", help="Comma-separated skill IDs to push")
    p_push.add_argument("--project", help="Project scope")

    # status
    sub.add_parser("status", help="Show sync status")

    args = parser.parse_args()

    if args.action == "pull":
        result = asyncio.run(pull_skills(
            repo=args.repo, skill_name=args.skill, force=args.force,
            branch=args.branch, project=args.project,
        ))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["success"] else 1)

    elif args.action == "push":
        from openspace.skill_engine.store import SkillStore
        store = SkillStore()
        try:
            ids = args.skill_ids.split(",") if args.skill_ids else None
            result = asyncio.run(push_skills(
                repo=args.repo, store=store, skill_ids=ids, project=args.project,
            ))
        finally:
            store.close()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["success"] else 1)

    elif args.action == "status":
        target = get_target_dir()
        manifest = _read_manifest(target)
        skills = manifest.get("skills", {})
        print(f"Target dir: {target}")
        print(f"Pulled skills: {len(skills)}")
        for name, info in skills.items():
            pulled_at = info.get("pulled_at", "?")
            repo = info.get("repo", "?")
            print(f"  {name} (from {repo}, pulled {pulled_at})")


if __name__ == "__main__":
    main()

