"""openspace-setup — one-command registration for AI tools.

Detects installed AI tools (Claude Code, Codex, Kiro) and registers
OpenSpace as an MCP server + copies host skills to the shared hub.

Usage:
    openspace-setup          # auto-detect and register everything
    openspace-setup --skip-skills   # register MCP only, skip skill copy
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOST_SKILLS_DIR = Path(__file__).resolve().parent / "host_skills"
SHARED_SKILLS_HUB = Path.home() / ".agents" / "skills"

MCP_ENV = {
    "OPENSPACE_CLOUD_ENABLED": "false",
    "MCP_USE_ANONYMIZED_TELEMETRY": "false",
}


def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def _resolve_mcp_command() -> str:
    """Find openspace-mcp command — prefer short name, fallback to full path."""
    short = shutil.which("openspace-mcp")
    if short:
        return "openspace-mcp"
    # Fallback: look in the same venv as this script
    venv_bin = Path(sys.executable).parent / "openspace-mcp"
    if venv_bin.exists():
        return str(venv_bin)
    return "openspace-mcp"


def _print(icon: str, msg: str):
    print(f"  {icon} {msg}")


# --- Claude Code ---

def setup_claude_code() -> bool:
    if not _has_cmd("claude"):
        return False

    mcp_cmd = _resolve_mcp_command()

    # Check if already registered
    result = _run(["claude", "mcp", "list"])
    if "openspace" in (result.stdout or ""):
        _print("~", "Claude Code: openspace already registered, updating...")
        _run(["claude", "mcp", "remove", "openspace", "-s", "user"])

    env_args = []
    for k, v in MCP_ENV.items():
        env_args.extend(["-e", f"{k}={v}"])

    result = _run(
        ["claude", "mcp", "add", "openspace", "-s", "user"]
        + env_args
        + ["--", mcp_cmd]
    )
    if result.returncode == 0:
        _print("OK", "Claude Code: MCP server registered (user scope)")
        return True
    else:
        _print("!!", f"Claude Code: registration failed — {result.stderr.strip()}")
        return False


# --- Codex ---

def setup_codex() -> bool:
    if not _has_cmd("codex"):
        return False

    mcp_cmd = _resolve_mcp_command()

    # Check if already registered
    result = _run(["codex", "mcp", "list"])
    if "openspace" in (result.stdout or ""):
        _print("~", "Codex: openspace already registered, updating...")
        _run(["codex", "mcp", "remove", "openspace"])

    env_args = []
    for k, v in MCP_ENV.items():
        env_args.extend(["--env", f"{k}={v}"])

    result = _run(
        ["codex", "mcp", "add", "openspace"]
        + env_args
        + ["--", mcp_cmd]
    )
    if result.returncode == 0:
        _print("OK", "Codex: MCP server registered")
        return True
    else:
        _print("!!", f"Codex: registration failed — {result.stderr.strip()}")
        return False


# --- Kiro ---

def setup_kiro() -> bool:
    kiro_dir = Path.home() / ".kiro"
    if not kiro_dir.exists():
        return False

    mcp_config_dir = kiro_dir / "settings"
    mcp_config_dir.mkdir(parents=True, exist_ok=True)
    mcp_config_path = mcp_config_dir / "mcp.json"

    # Load existing config or start fresh
    existing = {}
    if mcp_config_path.exists():
        try:
            existing = json.loads(mcp_config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    servers = existing.get("mcpServers", {})
    servers["openspace"] = {
        "command": _resolve_mcp_command(),
        "args": [],
        "env": MCP_ENV,
    }
    existing["mcpServers"] = servers

    mcp_config_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _print("OK", f"Kiro: MCP config written to {mcp_config_path}")
    return True


# --- Skills ---

def copy_host_skills() -> int:
    if not HOST_SKILLS_DIR.is_dir():
        _print("!!", f"Host skills directory not found: {HOST_SKILLS_DIR}")
        return 0

    SHARED_SKILLS_HUB.mkdir(parents=True, exist_ok=True)
    copied = 0

    for skill_dir in HOST_SKILLS_DIR.iterdir():
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        target = SHARED_SKILLS_HUB / skill_dir.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skill_dir, target)
        copied += 1

    if copied:
        _print("OK", f"Skills copied to {SHARED_SKILLS_HUB} ({copied} skills)")
    return copied


# --- .mcp.json ---

def write_project_mcp_json() -> bool:
    mcp_json_path = Path.cwd() / ".mcp.json"
    if mcp_json_path.exists():
        _print("~", ".mcp.json already exists, skipping")
        return False

    config = {
        "mcpServers": {
            "openspace": {
                "command": "openspace-mcp",
                "env": MCP_ENV,
            }
        }
    }
    mcp_json_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _print("OK", ".mcp.json written to current project")
    return True


# --- Main ---

def main():
    skip_skills = "--skip-skills" in sys.argv

    print("\nOpenSpace Setup\n")

    registered = []
    not_found = []

    for name, fn in [("Claude Code", setup_claude_code), ("Codex", setup_codex), ("Kiro", setup_kiro)]:
        result = fn()
        if result:
            registered.append(name)
        elif result is False and not _has_cmd(name.lower().replace(" ", "")):
            not_found.append(name)

    if not skip_skills:
        copy_host_skills()

    write_project_mcp_json()

    print()
    if registered:
        print(f"  Ready! OpenSpace registered for: {', '.join(registered)}")
    if not_found:
        print(f"  Not found: {', '.join(not_found)} (install them to enable)")
    print()


if __name__ == "__main__":
    main()
