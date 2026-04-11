"""OpenSpace MCP Server

Exposes the following tools to MCP clients:
  execute_task   — Delegate a task (auto-registers skills, auto-evolves)
  search_skills  — Search local skill registry
  fix_skill      — Manually fix a broken skill (FIX only; DERIVED/CAPTURED via execute_task)

Usage:
    python -m openspace.mcp_server                     # stdio (default)
    python -m openspace.mcp_server --transport sse     # SSE on port 8080
    python -m openspace.mcp_server --port 9090         # SSE on custom port

Environment variables: see ``openspace/host_detection/``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sys
import traceback
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

_real_stdout = sys.stdout
sys.stdout = _MCPSafeStdout(_real_stdout, sys.stderr)

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

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
        from openspace.host_detection import build_llm_kwargs, build_grounding_config_path

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



async def _auto_register_skill_dirs(skill_dirs: List[str]) -> int:
    """Register bot skill directories into OpenSpace's SkillRegistry + DB.

    Called automatically by ``execute_task`` when ``skill_dirs`` is provided.
    Already-registered directories are skipped (idempotent within a session).
    """
    global _registered_skill_dirs

    new_dirs = [
        Path(d) for d in skill_dirs
        if d not in _registered_skill_dirs and Path(d).is_dir()
    ]
    if not new_dirs:
        return 0

    openspace = await _get_openspace()
    registry = openspace._skill_registry
    if not registry:
        logger.warning("_auto_register_skill_dirs: SkillRegistry not initialized")
        return 0

    added = registry.discover_from_dirs(new_dirs)

    db_created = 0
    if added:
        store = _get_store()
        db_created = await store.sync_from_registry(added)

    for d in skill_dirs:
        _registered_skill_dirs.add(d)

    if added:
        logger.info(
            f"Auto-registered {len(added)} skill(s) from {len(new_dirs)} dir(s), "
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

    # Format evolved_skills
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


# MCP Tools (4 tools)
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
    Set MCP client tool-call timeout >= 600 seconds.

    Args:
        task: The task instruction (natural language).
        workspace_dir: Working directory. Defaults to OPENSPACE_WORKSPACE env.
        max_iterations: Max agent iterations (default: 20).
        skill_dirs: Bot's skill directories to auto-register so OpenSpace
                    can select and track them.  Already-registered dirs are
                    silently skipped.
    """
    try:
        openspace = await _get_openspace()

        # Auto-register bot skill directories
        if skill_dirs:
            await _auto_register_skill_dirs(skill_dirs)

        # Execute
        result = await openspace.execute(
            task=task,
            workspace_dir=workspace_dir,
            max_iterations=max_iterations,
        )

        formatted = _format_task_result(result)
        return _json_ok(formatted)

    except Exception as e:
        logger.error(f"execute_task failed: {e}", exc_info=True)
        return _json_error(e, status="error", traceback=traceback.format_exc(limit=5))


@mcp.tool()
async def search_skills(
    query: str,
    limit: int = 20,
) -> str:
    """Search skills in the local registry.

    Uses hybrid ranking: BM25 + embedding re-rank.
    Embedding requires a local fastembed model or EMBEDDING_BASE_URL;
    falls back to BM25-only without it.

    Args:
        query: Search query text (natural language or keywords).
        limit: Maximum results to return (default: 20).
    """
    try:
        from openspace.cloud.search import hybrid_search_skills

        q = query.strip()
        if not q:
            return _json_ok({"results": [], "count": 0})

        # Resolve local skills + store
        local_skills = None
        store = None
        openspace = await _get_openspace()
        registry = openspace._skill_registry
        if registry:
            local_skills = registry.list_skills()
            store = _get_store()

        results = await hybrid_search_skills(
            query=q,
            local_skills=local_skills,
            store=store,
            source="local",
            limit=limit,
        )

        output: Dict[str, Any] = {"results": results, "count": len(results)}
        return _json_ok(output)

    except Exception as e:
        logger.error(f"search_skills failed: {e}", exc_info=True)
        return _json_error(e)


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

    After fixing, the new skill is saved locally.

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

        # Step 4: Return result
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
        return _json_error(e, status="error", traceback=traceback.format_exc(limit=5))


def run_mcp_server() -> None:
    """Console-script entry point for ``openspace-mcp``."""
    import argparse

    parser = argparse.ArgumentParser(description="OpenSpace MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", sse_params={"port": args.port})
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_mcp_server()
