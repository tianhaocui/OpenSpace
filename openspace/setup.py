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
CODEX_HOOKS_DIR = Path(__file__).resolve().parent / "codex_hooks"

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


def setup_codex_hooks() -> bool:
    """Enable Codex event hooks and install the OpenSpace stop hook."""
    if not _has_cmd("codex"):
        return False

    codex_home = Path.home() / ".codex"
    if not codex_home.exists():
        return False

    # 1. Enable features.codex_hooks in config.toml
    config_path = codex_home / "config.toml"
    if config_path.exists():
        content = config_path.read_text(encoding="utf-8")
        if "codex_hooks" not in content:
            # Append or insert into [features] section
            if "[features]" in content:
                content = content.replace(
                    "[features]", "[features]\ncodex_hooks = true", 1
                )
            else:
                content += "\n[features]\ncodex_hooks = true\n"
            config_path.write_text(content, encoding="utf-8")
            _print("OK", "Codex: enabled features.codex_hooks in config.toml")
    else:
        config_path.write_text(
            "[features]\ncodex_hooks = true\n", encoding="utf-8"
        )
        _print("OK", "Codex: created config.toml with features.codex_hooks")

    # 2. Copy stop_hook.py to ~/.codex/openspace/
    hook_script_src = CODEX_HOOKS_DIR / "stop_hook.py"
    if not hook_script_src.exists():
        _print("!!", "Codex: stop_hook.py not found in package")
        return False

    hook_dest_dir = codex_home / "openspace"
    hook_dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(hook_script_src, hook_dest_dir / "stop_hook.py")

    # 3. Write/merge hooks.json
    hooks_path = codex_home / "hooks.json"
    hook_command = f"python3 {hook_dest_dir / 'stop_hook.py'}"

    openspace_hook_entry = {
        "type": "command",
        "command": hook_command,
        "statusMessage": "Reporting skill usage to OpenSpace...",
    }

    existing: dict = {}
    if hooks_path.exists():
        try:
            existing = json.loads(hooks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    hooks = existing.setdefault("hooks", {})
    stop_groups = hooks.setdefault("Stop", [])

    # Check if OpenSpace hook already registered
    already = False
    for group in stop_groups:
        for h in group.get("hooks", []):
            if "openspace" in h.get("command", "").lower():
                already = True
                h["command"] = hook_command  # update path
                break

    if not already:
        stop_groups.append({"hooks": [openspace_hook_entry]})

    hooks_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _print("OK", f"Codex: hooks.json written to {hooks_path}")
    return True


def setup_claude_code_hooks() -> bool:
    """Install the OpenSpace stop hook into Claude Code settings."""
    claude_home = Path.home() / ".claude"
    if not claude_home.exists():
        return False

    # 1. Copy stop_hook.py to ~/.claude/openspace/
    hook_script_src = CODEX_HOOKS_DIR / "stop_hook.py"
    if not hook_script_src.exists():
        _print("!!", "Claude Code: stop_hook.py not found in package")
        return False

    hook_dest_dir = claude_home / "openspace"
    hook_dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(hook_script_src, hook_dest_dir / "stop_hook.py")

    # 2. Merge into ~/.claude/settings.json
    settings_path = claude_home / "settings.json"
    hook_command = f"python3 {hook_dest_dir / 'stop_hook.py'}"

    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    hooks = existing.setdefault("hooks", {})
    stop_groups = hooks.setdefault("Stop", [])

    # Check if OpenSpace hook already registered
    already = False
    for group in stop_groups:
        for h in group.get("hooks", []):
            if "openspace" in h.get("command", "").lower():
                already = True
                h["command"] = hook_command  # update path
                break

    if not already:
        stop_groups.append({
            "hooks": [{
                "type": "command",
                "command": hook_command,
                "timeout": 15000,
            }],
        })

    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _print("OK", f"Claude Code: Stop hook added to {settings_path}")
    return True


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


def dedup_skill_dirs() -> int:
    """Replace duplicate skills in agent dirs with symlinks to ~/.agents/skills/.

    Ensures ~/.agents/skills/ is the single source of truth.  Skills that
    only exist in an agent dir are moved to agents first, then symlinked.
    """
    agents_dir = Path.home() / ".agents" / "skills"
    if not agents_dir.exists():
        return 0

    agent_dirs = [
        Path.home() / ".codex" / "skills",
        Path.home() / ".claude" / "skills",
        Path.home() / ".kiro" / "skills",
    ]
    replaced = 0
    for agent_dir in agent_dirs:
        if not agent_dir.exists():
            continue
        for skill_dir in sorted(agent_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith(".") or skill_dir.is_symlink():
                continue
            source = agents_dir / skill_dir.name
            if not source.exists():
                shutil.copytree(skill_dir, source)
            shutil.rmtree(skill_dir)
            skill_dir.symlink_to(source)
            replaced += 1
    return replaced


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

    # Configure event hooks for auto skill evolution
    setup_codex_hooks()
    setup_claude_code_hooks()

    if not skip_skills:
        copy_host_skills()

    write_project_mcp_json(mcp_cmd)

    # Deduplicate skill directories — ensure ~/.agents/skills/ is source of truth
    deduped = dedup_skill_dirs()
    if deduped:
        _print("OK", f"Deduplicated {deduped} skill(s) → symlinks to ~/.agents/skills/")

    print()
    if registered:
        print(f"  Ready! OpenSpace registered for: {', '.join(registered)}")
    if not_found:
        print(f"  Not found: {', '.join(not_found)} (install them to enable)")
    print()


if __name__ == "__main__":
    main()