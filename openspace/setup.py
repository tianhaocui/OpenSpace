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

from openspace.host_detection.skill_dirs import _SHARED_HUB as SHARED_SKILLS_HUB

HOST_SKILLS_DIR = Path(__file__).resolve().parent / "host_skills"

_LLM_PROVIDERS = [
    ("anthropic", "Anthropic (Claude Sonnet 4)", "ANTHROPIC_API_KEY", "anthropic/claude-sonnet-4-20250514"),
    ("anthropic-opus", "Anthropic (Claude Opus 4.6)", "ANTHROPIC_API_KEY", "anthropic/claude-opus-4-6-20250610"),
    ("openai", "OpenAI (GPT-4o)", "OPENAI_API_KEY", "openai/gpt-4o"),
    ("deepseek", "DeepSeek", "DEEPSEEK_API_KEY", "deepseek/deepseek-chat"),
    ("custom", "Custom endpoint", None, None),
]

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


def configure_llm() -> dict[str, str]:
    """Interactive LLM provider selection. Returns env vars to merge into MCP_ENV."""
    env: dict[str, str] = {}

    print("  LLM Configuration")
    print("  " + "\u2500" * 17)
    for i, (_key, label, _env_name, model) in enumerate(_LLM_PROVIDERS, 1):
        hint = f" ({model})" if model else ""
        print(f"    {i}. {label}{hint}")

    print()
    choice = input("  Choose provider [1]: ").strip() or "1"
    try:
        idx = max(0, min(int(choice) - 1, len(_LLM_PROVIDERS) - 1))
    except ValueError:
        idx = 0

    key, _label, env_key_name, default_model = _LLM_PROVIDERS[idx]

    # Model
    if default_model:
        model_input = input(f"  Model [{default_model}]: ").strip()
        model = model_input or default_model
    else:
        model = input("  Model (e.g. anthropic/claude-sonnet-4-20250514): ").strip()
        if not model:
            _print("!!", "No model specified, skipping LLM config")
            return env

    env["OPENSPACE_MODEL"] = model

    # API key
    if key == "custom":
        api_key = input("  API key: ").strip()
        if api_key:
            env["OPENSPACE_LLM_API_KEY"] = api_key
        api_base = input("  API base URL: ").strip()
        if api_base:
            env["OPENSPACE_LLM_API_BASE"] = api_base
        _print("OK", f"LLM: {model}")
    else:
        existing_key = os.environ.get(env_key_name, "").strip()
        if existing_key:
            masked = existing_key[:8] + "..." + existing_key[-4:] if len(existing_key) > 12 else "***"
            use_existing = input(f"  {env_key_name} found ({masked}). Use it? [Y/n]: ").strip().lower()
            if use_existing not in ("n", "no"):
                env[env_key_name] = existing_key
                _print("OK", f"LLM: {model} (using existing {env_key_name})")
                print()
                return env

        api_key = input(f"  {env_key_name}: ").strip()
        if api_key:
            env[env_key_name] = api_key
            _print("OK", f"LLM: {model}")
        else:
            _print("~", f"LLM: {model} (set {env_key_name} before running)")

    print()
    return env


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
    non_interactive = "--non-interactive" in sys.argv or "--yes" in sys.argv
    mcp_cmd = _resolve_mcp_command()

    print("\nOpenSpace Setup\n")

    # Step 1: LLM configuration
    if not non_interactive:
        llm_env = configure_llm()
        MCP_ENV.update(llm_env)

    # Step 2: Register with host agents
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

    # Step 3: Copy skills
    if not skip_skills:
        copy_host_skills()

    # Step 4: Write .mcp.json
    write_project_mcp_json(mcp_cmd)

    print()
    if registered:
        print(f"  Ready! OpenSpace registered for: {', '.join(registered)}")
    if MCP_ENV.get("OPENSPACE_MODEL"):
        print(f"  Model: {MCP_ENV['OPENSPACE_MODEL']}")
    if not_found:
        print(f"  Not found: {', '.join(not_found)} (install them to enable)")
    print()


if __name__ == "__main__":
    main()