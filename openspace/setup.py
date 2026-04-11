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

# Supported LLM providers for interactive setup
_LLM_PROVIDERS = [
    ("anthropic", "Anthropic (Claude)", "ANTHROPIC_API_KEY", "anthropic/claude-sonnet-4-20250514"),
    ("anthropic-opus", "Anthropic (Claude Opus)", "ANTHROPIC_API_KEY", "anthropic/claude-opus-4-20250514"),
    ("openai", "OpenAI (GPT)", "OPENAI_API_KEY", "openai/gpt-4o"),
    ("deepseek", "DeepSeek", "DEEPSEEK_API_KEY", "deepseek/deepseek-chat"),
    ("ollama", "Ollama (local)", None, "ollama/qwen3-coder:30b"),
    ("custom", "Custom (manual config)", None, None),
]

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


# --- LLM Configuration ---

def configure_llm() -> dict[str, str]:
    """Interactive LLM provider selection. Returns env vars to add to MCP_ENV."""
    env = {}

    print("  LLM Configuration")
    print("  ─────────────────")
    for i, (key, label, _, model) in enumerate(_LLM_PROVIDERS, 1):
        model_hint = f" ({model})" if model else ""
        print(f"    {i}. {label}{model_hint}")

    print()
    choice = input("  Choose provider [1]: ").strip()
    if not choice:
        choice = "1"

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(_LLM_PROVIDERS):
            idx = 0
    except ValueError:
        idx = 0

    key, label, env_key_name, default_model = _LLM_PROVIDERS[idx]

    # Ask for model override
    if default_model:
        model_input = input(f"  Model [{default_model}]: ").strip()
        model = model_input or default_model
    else:
        model = input("  Model (e.g. anthropic/claude-sonnet-4-20250514): ").strip()
        if not model:
            print("  !! No model specified, skipping LLM config")
            return env

    env["OPENSPACE_MODEL"] = model

    # Ask for API key
    if key == "ollama":
        # Ollama doesn't need an API key, but needs base URL
        base = input("  Ollama URL [http://127.0.0.1:11434]: ").strip()
        if base:
            env["OLLAMA_API_BASE"] = base
        _print("OK", f"LLM: {model} (Ollama local)")
    elif key == "custom":
        api_key = input("  API key: ").strip()
        if api_key:
            env["OPENSPACE_LLM_API_KEY"] = api_key
        api_base = input("  API base URL (optional): ").strip()
        if api_base:
            env["OPENSPACE_LLM_API_BASE"] = api_base
        _print("OK", f"LLM: {model} (custom)")
    else:
        # Check if key already exists in environment
        existing_key = os.environ.get(env_key_name, "").strip()
        if existing_key:
            masked = existing_key[:8] + "..." + existing_key[-4:]
            use_existing = input(f"  {env_key_name} found ({masked}). Use it? [Y/n]: ").strip().lower()
            if use_existing not in ("n", "no"):
                env[env_key_name] = f"${{{env_key_name}}}"
                _print("OK", f"LLM: {model} (using existing {env_key_name})")
                print()
                return env

        api_key = input(f"  {env_key_name}: ").strip()
        if api_key:
            env[env_key_name] = api_key
            _print("OK", f"LLM: {model}")
        else:
            # Reference env var for runtime resolution
            env[env_key_name] = f"${{{env_key_name}}}"
            _print("~", f"LLM: {model} (set {env_key_name} before running)")

    print()
    return env


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
    non_interactive = "--non-interactive" in sys.argv or "--yes" in sys.argv

    print("\nOpenSpace Setup\n")

    # Step 1: LLM configuration
    llm_env = {}
    if not non_interactive:
        llm_env = configure_llm()
    MCP_ENV.update(llm_env)

    # Step 2: Register with host agents
    registered = []
    not_found = []

    for name, fn in [("Claude Code", setup_claude_code), ("Codex", setup_codex), ("Kiro", setup_kiro)]:
        result = fn()
        if result:
            registered.append(name)
        elif result is False and not _has_cmd(name.lower().replace(" ", "")):
            not_found.append(name)

    # Step 3: Copy skills
    if not skip_skills:
        copy_host_skills()

    # Step 4: Write .mcp.json
    write_project_mcp_json()

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
