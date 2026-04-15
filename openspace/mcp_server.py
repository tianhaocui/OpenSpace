"""OpenSpace MCP Server

Exposes the following tools to MCP clients:
  execute_task    — Delegate a task (auto-registers skills, auto-searches, auto-evolves)
  search_skills   — Standalone search across local skills
  fix_skill       — Manually fix a broken skill (FIX only; DERIVED/CAPTURED via execute_task)
  sync_skills_git — Bidirectional sync with Git repos via skillpull

Usage:
    python -m openspace.mcp_server                     # auto (TTY -> SSE, MCP host -> stdio)
    python -m openspace.mcp_server --transport sse     # SSE on port 8080
    python -m openspace.mcp_server --transport streamable-http  # Streamable HTTP on port 8080
    python -m openspace.mcp_server --port 9090         # SSE on custom port

Environment variables: see ``openspace/host_detection/`` and ``openspace/cloud/auth.py``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


class _MCPSafeStdout:
    """Stdout wrapper: binary (.buffer) → real stdout, text (.write) → stderr."""

    def __init__(self, real_stdout, stderr):
        self._real = real_stdout
        self._stderr = stderr

    @property
    def buffer(self):
        return self._real.buffer

    def fileno(self):
        return self._real.fileno()

    def write(self, s):
        return self._stderr.write(s)

    def writelines(self, lines):
        return self._stderr.writelines(lines)

    def flush(self):
        self._stderr.flush()
        self._real.flush()

    def isatty(self):
        return self._stderr.isatty()

    @property
    def encoding(self):
        return self._stderr.encoding

    @property
    def errors(self):
        return self._stderr.errors

    @property
    def closed(self):
        return self._stderr.closed

    def readable(self):
        return False

    def writable(self):
        return True

    def seekable(self):
        return False

    def __getattr__(self, name):
        return getattr(self._stderr, name)

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_real_stdout = sys.stdout

# Windows pipe buffers are small. When using stdio MCP transport,
# the parent process only reads stdout for MCP messages and does NOT
# drain stderr. Heavy log/print output during execute_task fills the stderr
# pipe buffer, blocking this process on write() → deadlock → timeout.
# Redirect stderr to a log file on Windows to prevent this.
if os.name == "nt":
    _stderr_file = open(
        _LOG_DIR / "mcp_stderr.log", "a", encoding="utf-8", buffering=1
    )
    sys.stderr = _stderr_file

sys.stdout = _MCPSafeStdout(_real_stdout, sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "mcp_server.log")],
)
logger = logging.getLogger("openspace.mcp_server")

from mcp.server.fastmcp import FastMCP

_fastmcp_kwargs: dict = {}
try:
    if "description" in inspect.signature(FastMCP.__init__).parameters:
        _fastmcp_kwargs["description"] = (
            "OpenSpace: Unite the Agents. Evolve the Mind. Rebuild the World."
        )
except (TypeError, ValueError):
    pass

mcp = FastMCP("OpenSpace", **_fastmcp_kwargs)

_openspace_instance = None
_openspace_lock = asyncio.Lock()
_standalone_store = None

# Internal state: tracks bot skill directories already registered this session.
_registered_skill_dirs: set = set()



async def _get_openspace():
    """Lazy-initialise the OpenSpace engine."""
    global _openspace_instance
    if _openspace_instance is not None and _openspace_instance.is_initialized():
        return _openspace_instance

    async with _openspace_lock:
        if _openspace_instance is not None and _openspace_instance.is_initialized():
            return _openspace_instance

        logger.info("Initializing OpenSpace engine ...")
        from openspace.tool_layer import OpenSpace, OpenSpaceConfig
        from openspace.host_detection import (
            build_grounding_config_path,
            build_llm_kwargs,
            load_runtime_env,
        )

        load_runtime_env()

        env_model = os.environ.get("OPENSPACE_MODEL", "")
        workspace = os.environ.get("OPENSPACE_WORKSPACE")
        max_iter = int(os.environ.get("OPENSPACE_MAX_ITERATIONS", "20"))
        enable_rec = os.environ.get("OPENSPACE_ENABLE_RECORDING", "true").lower() in ("true", "1", "yes")

        backend_scope_raw = os.environ.get("OPENSPACE_BACKEND_SCOPE")
        backend_scope = (
            [b.strip() for b in backend_scope_raw.split(",") if b.strip()]
            if backend_scope_raw else None
        )

        config_path = build_grounding_config_path()
        model, llm_kwargs = build_llm_kwargs(env_model)

        _pkg_root = str(Path(__file__).resolve().parent.parent)
        recording_base = workspace or _pkg_root
        recording_log_dir = str(Path(recording_base) / "logs" / "recordings")

        config = OpenSpaceConfig(
            llm_model=model,
            llm_kwargs=llm_kwargs,
            workspace_dir=workspace,
            grounding_max_iterations=max_iter,
            enable_recording=enable_rec,
            recording_backends=["shell"] if enable_rec else None, # ["shell", "mcp", "web"] if enable_rec else None
            recording_log_dir=recording_log_dir,
            backend_scope=backend_scope,
            grounding_config_path=config_path,
        )

        _openspace_instance = OpenSpace(config=config)
        await _openspace_instance.initialize()
        logger.info("OpenSpace engine ready (model=%s).", model)

        # Auto-register host bot skill directories from env (set once by human)
        host_skill_dirs_raw = os.environ.get("OPENSPACE_HOST_SKILL_DIRS", "")
        if host_skill_dirs_raw:
            dirs = [d.strip() for d in host_skill_dirs_raw.split(",") if d.strip()]
            if dirs:
                await _auto_register_skill_dirs(dirs)
                logger.info("Auto-registered host skill dirs from OPENSPACE_HOST_SKILL_DIRS: %s", dirs)

        return _openspace_instance


def _get_store():
    """Get SkillStore — reuses OpenSpace's internal instance when available."""
    global _standalone_store
    if _openspace_instance and _openspace_instance.is_initialized():
        internal = getattr(_openspace_instance, "_skill_store", None)
        if internal and not internal._closed:
            return internal
    if _standalone_store is None or _standalone_store._closed:
        from openspace.skill_engine import SkillStore
        _standalone_store = SkillStore()
    return _standalone_store


def _get_local_skill_registry():
    """Build a lightweight SkillRegistry for local-only skill search.

    This avoids initializing the full OpenSpace engine when callers only
    want to inspect local skills. It mirrors the skill directory discovery
    order used by the full engine, but skips LLM / provider startup.
    The registry is rebuilt per call so later local searches can see
    newly added skills without requiring a process restart.
    """
    from openspace.config import get_config
    from openspace.skill_engine import SkillRegistry

    skill_paths: List[Path] = []

    # Auto-detect agent skill directories
    from openspace.host_detection.skill_dirs import auto_detect_skill_dirs
    for p in auto_detect_skill_dirs():
        if p not in skill_paths:
            skill_paths.append(p)

    host_dirs_raw = os.environ.get("OPENSPACE_HOST_SKILL_DIRS", "")
    if host_dirs_raw:
        for d in host_dirs_raw.split(","):
            d = d.strip()
            if not d:
                continue
            p = Path(d)
            if p.exists():
                skill_paths.append(p)
            else:
                logger.warning("Host skill dir does not exist: %s", d)

    try:
        skill_cfg = get_config().skills
    except Exception as e:
        logger.warning("Failed to load local skill config: %s", e)
        skill_cfg = None

    if skill_cfg and skill_cfg.skill_dirs:
        for d in skill_cfg.skill_dirs:
            p = Path(d)
            if p in skill_paths:
                continue
            if p.exists():
                skill_paths.append(p)
            else:
                logger.warning("Configured skill dir does not exist: %s", d)

    builtin_skills = Path(__file__).resolve().parent / "skills"
    if builtin_skills.exists():
        skill_paths.append(builtin_skills)

    if not skill_paths:
        logger.debug("No local skill directories found")
        return None

    registry = SkillRegistry(skill_dirs=skill_paths)
    registry.discover()
    return registry


async def _auto_register_skill_dirs(skill_dirs: List[str]) -> int:
    """Register bot skill directories into OpenSpace's SkillRegistry + DB.

    Called automatically by ``execute_task`` on every invocation. Directories
    are re-scanned each time so that skills created by the host bot since the last call are discovered immediately.
    """
    global _registered_skill_dirs

    valid_dirs = [Path(d) for d in skill_dirs if Path(d).is_dir()]
    if not valid_dirs:
        return 0

    openspace = await _get_openspace()
    registry = openspace._skill_registry
    if not registry:
        logger.warning("_auto_register_skill_dirs: SkillRegistry not initialized")
        return 0

    added = registry.discover_from_dirs(valid_dirs)

    db_created = 0
    if added:
        store = _get_store()
        db_created = await store.sync_from_registry(added)

    is_first = any(d not in _registered_skill_dirs for d in skill_dirs)
    for d in skill_dirs:
        _registered_skill_dirs.add(d)

    if added:
        action = "Auto-registered" if is_first else "Re-scanned & found"
        logger.info(
            f"{action} {len(added)} skill(s) from {len(valid_dirs)} dir(s), "
            f"{db_created} new DB record(s)"
        )
    return len(added)


def _format_task_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Format an OpenSpace execution result for MCP transport."""
    tool_execs = result.get("tool_executions", [])
    tool_summary = [
        {
            "tool": te.get("tool_name", te.get("tool", "")),
            "status": te.get("status", ""),
            "error": te.get("error", "")[:200] if te.get("error") else None,
        }
        for te in tool_execs[:20]
    ]

    output: Dict[str, Any] = {
        "status": result.get("status", "unknown"),
        "response": result.get("response", ""),
        "execution_time": round(result.get("execution_time", 0), 2),
        "iterations": result.get("iterations", 0),
        "skills_used": result.get("skills_used", []),
        "task_id": result.get("task_id", ""),
        "tool_call_count": len(tool_execs),
        "tool_summary": tool_summary,
    }
    if result.get("warning"):
        output["warning"] = result["warning"]

    # Format evolved_skills with skill_dir
    raw_evolved = result.get("evolved_skills", [])
    if raw_evolved:
        formatted_evolved = []
        for es in raw_evolved:
            skill_path = es.get("path", "")
            skill_dir = str(Path(skill_path).parent) if skill_path else ""
            formatted_evolved.append({
                "skill_dir": skill_dir,
                "name": es.get("name", ""),
                "origin": es.get("origin", ""),
                "change_summary": es.get("change_summary", ""),
            })
        output["evolved_skills"] = formatted_evolved

    return output


def _json_ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _json_error(error: Any, **extra) -> str:
    return json.dumps({"error": str(error), **extra}, ensure_ascii=False)


# MCP Tools (5 tools)
@mcp.tool()
async def execute_task(
    task: str,
    workspace_dir: str | None = None,
    max_iterations: int | None = None,
    skill_dirs: list[str] | None = None,
) -> str:
    """Execute a task with OpenSpace's full grounding engine.

    OpenSpace will:
    1. Auto-register bot skills from skill_dirs (if provided)
    2. Search for relevant local skills
    3. Attempt skill-guided execution → fallback to pure tools
    4. Auto-analyze → auto-evolve (FIX/DERIVED/CAPTURED) if needed

    Note: This call blocks until the task completes (may take minutes).
    Set MCP client tool-call timeout ≥ 600 seconds.

    Args:
        task: The task instruction (natural language).
        workspace_dir: Working directory. Defaults to OPENSPACE_WORKSPACE env.
        max_iterations: Max agent iterations (default: 20).
        skill_dirs: Bot's skill directories to auto-register so OpenSpace
                    can select and track them.  Directories are re-scanned
                    on every call to discover skills created since the last
                    invocation.
    """
    try:
        openspace = await _get_openspace()

        # Re-scan host skill directories (from env) to pick up skills
        # created by the host bot since the last call.
        host_skill_dirs_raw = os.environ.get("OPENSPACE_HOST_SKILL_DIRS", "")
        if host_skill_dirs_raw:
            env_dirs = [d.strip() for d in host_skill_dirs_raw.split(",") if d.strip()]
            if env_dirs:
                await _auto_register_skill_dirs(env_dirs)

        # Auto-register bot skill directories (from call parameter)
        if skill_dirs:
            await _auto_register_skill_dirs(skill_dirs)

        # Determine where CAPTURED skills should be written.
        # Prefer the explicit skill_dirs parameter (= calling host agent's dir),
        # then fall back to the first env-based host skill dir.
        capture_skill_dir: str | None = None
        if skill_dirs:
            capture_skill_dir = skill_dirs[0]
        elif host_skill_dirs_raw:
            first_env = next(
                (d.strip() for d in host_skill_dirs_raw.split(",") if d.strip()),
                None,
            )
            if first_env:
                capture_skill_dir = first_env

        # Execute
        result = await openspace.execute(
            task=task,
            workspace_dir=workspace_dir,
            max_iterations=max_iterations,
            capture_skill_dir=capture_skill_dir,
        )

        formatted = _format_task_result(result)
        return _json_ok(formatted)

    except Exception as e:
        logger.error(f"execute_task failed: {e}", exc_info=True)
        return _json_error(e, status="error")


@mcp.tool()
async def search_skills(
    query: str,
    limit: int = 20,
    include_remote: bool = True,
) -> str:
    """Search skills across local registry and skills.sh community.

    Standalone search for browsing / discovery.  Use this when the bot
    wants to find available skills, then decide whether to handle the
    task locally or delegate to ``execute_task``.

    Local skills are ranked first (BM25 + embedding). When include_remote
    is True, results from skills.sh (Vercel's open agent skills directory)
    are appended after local results.

    Args:
        query: Search query text (natural language or keywords).
        limit: Maximum results to return (default: 20).
        include_remote: Search skills.sh for community skills (default: True).
    """
    try:
        from openspace.cloud.search import hybrid_search_skills

        q = query.strip()
        if not q:
            return _json_ok({"results": [], "count": 0})

        # Re-scan host skill directories so newly created skills are searchable.
        openspace = await _get_openspace()

        host_skill_dirs_raw = os.environ.get("OPENSPACE_HOST_SKILL_DIRS", "")
        if host_skill_dirs_raw:
            env_dirs = [d.strip() for d in host_skill_dirs_raw.split(",") if d.strip()]
            if env_dirs:
                await _auto_register_skill_dirs(env_dirs)

        registry = openspace._skill_registry
        local_skills = registry.list_skills() if registry else None
        store = _get_store() if registry else None

        results = await hybrid_search_skills(
            query=q,
            local_skills=local_skills,
            store=store,
            source="local",
            limit=limit,
            include_remote=include_remote,
        )

        output: Dict[str, Any] = {"results": results, "count": len(results)}
        return _json_ok(output)

    except Exception as e:
        logger.error(f"search_skills failed: {e}", exc_info=True)
        return _json_error(e)


async def _report_skill_usage_core(
    skill_name: str,
    skill_dir: str | None = None,
    task_completed: bool = True,
    skill_applied: bool = True,
    note: str = "",
) -> dict:
    """Core logic for reporting skill usage. Returns a result dict.

    Shared by the MCP tool and the CLI entry point.
    """
    from datetime import datetime
    from openspace.skill_engine.types import ExecutionAnalysis, SkillJudgment
    import uuid

    store = _get_store()

    # Resolve skill_id from name or path
    skill_id = None
    versions = store.get_versions(skill_name)
    if versions:
        active = [v for v in versions if v.is_active]
        rec = active[0] if active else versions[-1]
        skill_id = rec.skill_id
    elif skill_dir:
        rec = store.load_record_by_path(skill_dir)
        if rec:
            skill_id = rec.skill_id

    if not skill_id:
        raise ValueError(
            f"Skill '{skill_name}' not found in OpenSpace. "
            f"Register it first via execute_task(skill_dirs=[...]) or fix_skill()."
        )

    # Build and record analysis
    analysis = ExecutionAnalysis(
        task_id=f"external-{uuid.uuid4().hex[:12]}",
        timestamp=datetime.now(),
        task_completed=task_completed,
        execution_note=note or f"External usage of {skill_name}",
        skill_judgments=[
            SkillJudgment(
                skill_id=skill_id,
                skill_applied=skill_applied,
                note=note,
            ),
        ],
    )
    await store.record_analysis(analysis)

    # Reload record to get updated stats
    updated = store.load_record(skill_id)
    stats = {}
    if updated:
        stats = {
            "total_selections": updated.total_selections,
            "total_applied": updated.total_applied,
            "total_completions": updated.total_completions,
            "total_fallbacks": updated.total_fallbacks,
            "applied_rate": updated.applied_rate,
            "completion_rate": updated.completion_rate,
            "effective_rate": updated.effective_rate,
        }

    # Fast-path: consecutive failures → immediate evolution via Trigger 1
    # Bypasses the min_selections=5 gate so low-frequency skills can evolve.
    evolve_triggered = False
    if (not task_completed and skill_applied
            and updated and updated.total_selections >= 3):
        recent_analyses = store.load_analyses(skill_id=skill_id, limit=3)
        consecutive_fails = (
            len(recent_analyses) >= 3
            and all(
                not a.task_completed
                and any(j.skill_applied for j in a.skill_judgments
                        if j.skill_id == skill_id)
                for a in recent_analyses[-3:]
            )
        )
        if consecutive_fails:
            from openspace.skill_engine.types import EvolutionSuggestion, EvolutionType
            notes = [
                j.note for a in recent_analyses[-3:]
                for j in a.skill_judgments
                if j.skill_id == skill_id and j.note
            ]
            analysis.evolution_suggestions = [
                EvolutionSuggestion(
                    evolution_type=EvolutionType.FIX,
                    target_skill_ids=[skill_id],
                    direction=(
                        f"Skill failed 3 consecutive times. "
                        f"Notes: {'; '.join(notes[-3:]) or 'no details'}"
                    ),
                ),
            ]
            try:
                openspace = await _get_openspace()
                evolver = openspace._skill_evolver
                if evolver:
                    evolver.schedule_background(
                        evolver.process_analysis(analysis),
                        label=f"early_fix_{skill_id}",
                    )
                    evolve_triggered = True
                    logger.info(
                        f"report_skill_usage: early evolution triggered for "
                        f"'{skill_name}' (3 consecutive failures)"
                    )
            except Exception:
                pass  # best-effort

    # Trigger metric check if enough data accumulated (standard path)
    if not evolve_triggered and updated and updated.total_selections >= 5:
        try:
            openspace = await _get_openspace()
            evolver = openspace._skill_evolver
            if evolver:
                asyncio.get_event_loop().create_task(
                    evolver.process_metric_check(min_selections=5)
                )
                evolve_triggered = True
        except Exception:
            pass  # best-effort

    logger.info(
        f"report_skill_usage: {skill_name} ({skill_id}) "
        f"applied={skill_applied} completed={task_completed}"
    )

    return {
        "status": "recorded",
        "skill_id": skill_id,
        "skill_name": skill_name,
        "quality": stats,
        "evolve_triggered": evolve_triggered,
    }


@mcp.tool()
async def report_skill_usage(
    skill_name: str,
    skill_dir: str | None = None,
    task_completed: bool = True,
    skill_applied: bool = True,
    note: str = "",
) -> str:
    """Report external skill usage to OpenSpace's quality tracking system.

    Use this when a skill was executed outside of ``execute_task``
    (e.g. via Claude Code's native Skill system) and you want
    OpenSpace to track the usage for quality metrics and auto-evolution.

    Args:
        skill_name: Skill name (e.g. "git-commit"). Resolved to skill_id
                    via the store's version history.
        skill_dir: Optional path to the skill directory. Used as fallback
                   if skill_name resolution fails.
        task_completed: Whether the task completed successfully (default True).
        skill_applied: Whether the skill was actually applied (default True).
        note: Optional note about the execution.
    """
    try:
        result = await _report_skill_usage_core(
            skill_name=skill_name,
            skill_dir=skill_dir,
            task_completed=task_completed,
            skill_applied=skill_applied,
            note=note,
        )
        return _json_ok(result)
    except ValueError as e:
        return _json_error(str(e))
    except Exception as e:
        logger.error(f"report_skill_usage failed: {e}", exc_info=True)
        return _json_error(e, status="error")


@mcp.tool()
async def fix_skill(
    skill_dir: str,
    direction: str,
) -> str:
    """Manually fix a broken skill.

    This is the **only** manual evolution entry point.  DERIVED and
    CAPTURED evolutions are triggered automatically by ``execute_task``
    (they need a task to run).  Use ``fix_skill`` when:

      - A skill's instructions are wrong or outdated
      - The bot knows exactly which skill is broken and what to fix
      - Auto-evolution inside ``execute_task`` didn't catch the issue

    The skill does NOT need to be pre-registered in OpenSpace —
    provide the skill directory path and OpenSpace will register it
    automatically before fixing.

    Args:
        skill_dir: Path to the broken skill directory (must contain SKILL.md).
        direction: What's broken and how to fix it.  Be specific:
                   e.g. "The API endpoint changed from v1 to v2" or
                   "Add retry logic for HTTP 429 rate limit errors".
    """
    try:
        from openspace.skill_engine.types import EvolutionSuggestion, EvolutionType
        from openspace.skill_engine.evolver import EvolutionContext, EvolutionTrigger

        if not direction:
            return _json_error("direction is required — describe what to fix.")

        skill_path = Path(skill_dir)
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            return _json_error(f"SKILL.md not found in {skill_dir}")

        openspace = await _get_openspace()
        registry = openspace._skill_registry
        if not registry:
            return _json_error("SkillRegistry not initialized")
        if not openspace._skill_evolver:
            return _json_error("Skill evolution is not enabled")

        # Step 1: Register the skill (idempotent)
        meta = registry.register_skill_dir(skill_path)
        if not meta:
            return _json_error(f"Failed to register skill from {skill_dir}")

        store = _get_store()
        await store.sync_from_registry([meta])

        # Step 2: Load record + content
        rec = store.load_record(meta.skill_id)
        if not rec:
            return _json_error(f"Failed to load skill record for {meta.skill_id}")

        evolver = openspace._skill_evolver
        content = evolver._load_skill_content(rec)
        if not content:
            return _json_error(f"Cannot load content for skill: {meta.skill_id}")

        # Step 3: Run FIX evolution
        recent = store.load_analyses(skill_id=meta.skill_id, limit=5)

        ctx = EvolutionContext(
            trigger=EvolutionTrigger.ANALYSIS,
            suggestion=EvolutionSuggestion(
                evolution_type=EvolutionType.FIX,
                target_skill_ids=[meta.skill_id],
                direction=direction,
            ),
            skill_records=[rec],
            skill_contents=[content],
            skill_dirs=[skill_path],
            recent_analyses=recent,
            available_tools=evolver._available_tools,
        )

        logger.info(f"fix_skill: {meta.skill_id} — {direction[:100]}")
        new_record = await evolver.evolve(ctx)

        if not new_record:
            return _json_ok({
                "status": "failed",
                "error": "Evolution did not produce a new skill.",
            })

        new_skill_dir = Path(new_record.path).parent if new_record.path else skill_path
        return _json_ok({
            "status": "success",
            "new_skill": {
                "skill_dir": str(new_skill_dir),
                "name": new_record.name,
                "origin": new_record.lineage.origin.value,
                "change_summary": new_record.lineage.change_summary,
            },
        })

    except Exception as e:
        logger.error(f"fix_skill failed: {e}", exc_info=True)
        return _json_error(e, status="error")


@mcp.tool()
async def sync_skills_git(
    action: str,
    repo: str | None = None,
    skill_name: str | None = None,
    skill_ids: list[str] | None = None,
    force: bool = False,
    project: str | None = None,
    branch: str | None = None,
) -> str:
    """Sync skills with a Git repository via skillpull CLI.

    Skills are pulled into / pushed from the host agent's skill directory
    (read from ``OPENSPACE_HOST_SKILL_DIRS``).  No separate OpenSpace
    skill directory is needed.

    Two actions:
      "pull"  — Pull skills from a Git repo and register them in OpenSpace
                (quality tracking, intelligent selection, auto-evolution).
      "push"  — Export evolved OpenSpace skills and push them to a Git repo
                so team members can ``skillpull pull`` to get improvements.

    Requires ``skillpull`` CLI installed (npm i -g skillpull).

    Args:
        action: "pull" or "push".
        repo: Git repo URL, user/repo shortname, or @alias.
              Defaults to skillpull's configured registry.
        skill_name: Pull only this specific skill (pull action only).
        skill_ids: Skill IDs to export and push (push action only).
                   If omitted, pushes all evolved skills.
        force: Overwrite existing skills on pull.
        project: Project scope for skillpull (maps to .skillpullrc project).
        branch: Git branch/tag to pull from.
    """
    try:
        from openspace.cloud.cli.skillpull_sync import (
            pull_and_register,
            push_skills,
        )

        if action == "pull":
            openspace = await _get_openspace()
            registry = openspace._skill_registry
            if not registry:
                return _json_error("SkillRegistry not initialized")
            store = _get_store()

            result = await pull_and_register(
                registry, store,
                repo=repo, skill_name=skill_name, force=force,
                branch=branch, project=project,
            )
            return _json_ok(result) if result.get("success") else _json_error(result.get("error", "pull failed"))

        elif action == "push":
            store = _get_store()
            result = await push_skills(
                repo=repo, store=store, skill_ids=skill_ids, project=project,
            )
            return _json_ok(result) if result.get("success") else _json_error(result.get("error", "push failed"))

        else:
            return _json_error(f"Unknown action: {action}. Use 'pull' or 'push'.")

    except FileNotFoundError as e:
        return _json_error(str(e))
    except Exception as e:
        logger.error(f"sync_skills_git failed: {e}", exc_info=True)
        return _json_error(e, status="error")


def run_mcp_server() -> None:
    """Console-script entry point for ``openspace-mcp``."""
    import argparse

    def _port_flag_was_set(argv: list[str]) -> bool:
        return any(arg == "--port" or arg.startswith("--port=") for arg in argv)

    def _parse_port_from_env(default: int = 8080) -> int:
        raw_port = os.environ.get("OPENSPACE_MCP_PORT", "").strip()
        if not raw_port:
            return default
        try:
            return int(raw_port)
        except ValueError:
            logger.warning(
                "Ignoring invalid OPENSPACE_MCP_PORT=%r; falling back to %d.",
                raw_port,
                default,
            )
            return default

    def _parse_host_from_env(default: str = "127.0.0.1") -> str:
        return os.environ.get("OPENSPACE_MCP_HOST", "").strip() or default

    def _resolve_transport(requested_transport: str, argv: list[str]) -> str:
        if requested_transport in ("stdio", "sse", "streamable-http"):
            return requested_transport

        env_transport = os.environ.get("OPENSPACE_MCP_TRANSPORT", "").strip().lower()
        if env_transport:
            if env_transport in ("stdio", "sse", "streamable-http"):
                return env_transport
            logger.warning(
                "Ignoring invalid OPENSPACE_MCP_TRANSPORT=%r; expected 'stdio', 'sse', or 'streamable-http'.",
                env_transport,
            )

        # Treat an explicit port override as an HTTP/SSE intent. This keeps the
        # CLI behavior aligned with the usage examples above.
        if _port_flag_was_set(argv):
            return "sse"

        stdin_is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        stdout_is_tty = _real_stdout.isatty()
        return "sse" if stdin_is_tty and stdout_is_tty else "stdio"

    argv = sys.argv[1:]
    parser = argparse.ArgumentParser(description="OpenSpace MCP Server")
    parser.add_argument(
        "--transport",
        choices=["auto", "stdio", "sse", "streamable-http"],
        default="auto",
    )
    parser.add_argument("--host", default=_parse_host_from_env())
    parser.add_argument("--port", type=int, default=_parse_port_from_env())
    args = parser.parse_args(argv)

    transport = _resolve_transport(args.transport, argv)

    if transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        logger.info("Starting OpenSpace MCP server with SSE transport on port %s", args.port)
        mcp.run(transport="sse")
    elif transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        logger.info(
            "Starting OpenSpace MCP server with streamable HTTP transport on %s:%s",
            args.host,
            args.port,
        )
        mcp.run(transport="streamable-http")
    else:
        logger.info("Starting OpenSpace MCP server with stdio transport")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_mcp_server()


def run_report_usage() -> None:
    """Console-script entry point for ``openspace-report``.

    Usage:
        openspace-report <skill_name> [--failed] [--not-applied] [--note "..."]
        openspace-report git-commit
        openspace-report git-commit --failed --note "hook rejected the commit"
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Report skill usage to OpenSpace quality tracking",
        prog="openspace-report",
    )
    parser.add_argument("skill_name", help="Skill name (e.g. git-commit)")
    parser.add_argument("--skill-dir", default=None, help="Skill directory path (fallback)")
    parser.add_argument("--failed", action="store_true", help="Mark task as failed")
    parser.add_argument("--not-applied", action="store_true", help="Mark skill as not applied")
    parser.add_argument("--note", default="", help="Optional note")
    args = parser.parse_args()

    async def _run():
        try:
            result = await _report_skill_usage_core(
                skill_name=args.skill_name,
                skill_dir=args.skill_dir,
                task_completed=not args.failed,
                skill_applied=not args.not_applied,
                note=args.note,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except ValueError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)

    asyncio.run(_run())
