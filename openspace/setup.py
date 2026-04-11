"""openspace-setup — one-command registration for AI tools.

Detects installed AI tools (Claude Code, Codex, Kiro) and registers
OpenSpace as an MCP server + copies host skills to the shared hub.

Usage:
    openspace-setup          # auto-detect and register everything
    openspace-setup --skip-skills   # register MCP only, skip skill copy
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from openspace.host_detection.skill_dirs import _SHARED_HUB as SHARED_SKILLS_HUB

HOST_SKILLS_DIR = Path(__file__).resolve().parent / "host_skills"

MCP_ENV = {
    "OPENSPACE_CLOUD_ENABLED": "false",
    "MCP_USE_ANONYMIZED_TELEMETRY": "false",
}

# Map display names to CLI binary names
_TOOL_BINARIES = {
    "Claude Code": "claude",
    "Codex": "codex",
    "Kiro": "kiro",
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def _resolve_mcp_command() -> str:
    """Find openspace-mcp — prefer PATH, fallback to sibling of this Python."""
    if shutil.which("openspace-mcp"):
        return "openspace-mcp"
    venv_bin = Path(sys.executable).parent / "openspace-mcp"
    if venv_bin.exists():
        return str(venv_bin)
    return "openspace-mcp"


def _print(icon: str, msg: str):
    print(f"  {icon} {msg}")


def _is_server_registered(stdout: str, name: str = "openspace") -> bool:
    """Check if a server is registered by matching whole-word in CLI output."""
    for line in (stdout or "").splitlines():
        tokens = line.split()
        if tokens and tokens[0].rstrip(":") == name:
            return True
    return False


def _setup_cli_tool(
    binary: str,
    label: str,
    mcp_cmd: str,
    env_flag: str,
    scope_args: list[str] | None = None,
) -> bool:
    """Register OpenSpace MCP server with a CLI-based AI tool."""
    if not _has_cmd(binary):
        return False

    result = _run([binary, "mcp", "list"])
    if _is_server_registered(result.stdout):
        _print("~", f"{label}: openspace already registered, updating...")
        _run([binary, "mcp", "remove", "openspace"] + (scope_args or []))

    env_args = []
    for k, v in MCP_ENV.items():
        env_args.extend([env_flag, f"{k}={v}"])

    add_cmd = [binary, "mcp", "add", "openspace"] + (scope_args or []) + env_args + ["--", mcp_cmd]
    result = _run(add_cmd)

    if result.returncode == 0:
        _print("OK", f"{label}: MCP server registered")
        return True
    _print("!!", f"{label}: registration failed — {result.stderr.strip()}")
    return False


def setup_claude_code(mcp_cmd: str) -> bool:
    return _setup_cli_tool("claude", "Claude Code", mcp_cmd, "-e", ["-s", "user"])


def setup_codex(mcp_cmd: str) -> bool:
    return _setup_cli_tool("codex", "Codex", mcp_cmd, "--env")


def setup_kiro(mcp_cmd: str) -> bool:
    kiro_dir = Path.home() / ".kiro"
    if not kiro_dir.exists():
        return False

    mcp_config_dir = kiro_dir / "settings"
    mcp_config_dir.mkdir(parents=True, exist_ok=True)
    mcp_config_path = mcp_config_dir / "mcp.json"

    existing = {}
    if mcp_config_path.exists():
        try:
            existing = json.loads(mcp_config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    servers = existing.get("mcpServers", {})
    servers["openspace"] = {"command": mcp_cmd, "args": [], "env": MCP_ENV}
    existing["mcpServers"] = servers

    mcp_config_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _print("OK", f"Kiro: MCP config written to {mcp_config_path}")
    return True


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


def write_project_mcp_json(mcp_cmd: str) -> bool:
    mcp_json_path = Path.cwd() / ".mcp.json"
    if mcp_json_path.exists():
        _print("~", ".mcp.json already exists, skipping")
        return False

    config = {"mcpServers": {"openspace": {"command": mcp_cmd, "env": MCP_ENV}}}
    mcp_json_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _print("OK", ".mcp.json written to current project")
    return True


def main():
    skip_skills = "--skip-skills" in sys.argv
    mcp_cmd = _resolve_mcp_command()

    print("\nOpenSpace Setup\n")

    registered = []
    not_found = []

    tools = [
        ("Claude Code", setup_claude_code),
        ("Codex", setup_codex),
        ("Kiro", setup_kiro),
    ]
    for name, fn in tools:
        result = fn(mcp_cmd)
        if result:
            registered.append(name)
        elif not _has_cmd(_TOOL_BINARIES.get(name, "")):
            not_found.append(name)

    if not skip_skills:
        copy_host_skills()

    write_project_mcp_json(mcp_cmd)

    print()
    if registered:
        print(f"  Ready! OpenSpace registered for: {', '.join(registered)}")
    if not_found:
        print(f"  Not found: {', '.join(not_found)} (install them to enable)")
    print()


if __name__ == "__main__":
    main()