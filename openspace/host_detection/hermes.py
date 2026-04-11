"""Hermes Agent host-agent config reader.

Reads ``~/.hermes/config.yaml`` to auto-detect:
  - LLM provider credentials (``model.api_key``, ``model.base_url``, ``model.provider``)
  - MCP server env block for the ``openspace`` server (``mcp_servers.openspace.env``)
  - Default model and provider settings

Config path resolution:
  1. ``HERMES_CONFIG_PATH`` env var
  2. ``HERMES_HOME/config.yaml``
  3. ``~/.hermes/config.yaml`` (default)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("openspace.host_detection")

# Provider name → Hermes config key mapping for credential extraction.
# Hermes stores API keys in env vars (`.env` file), not in config.yaml,
# so we map provider names to the env var names Hermes uses.
_HERMES_PROVIDER_ENV_KEYS: Dict[str, tuple[str, ...]] = {
    "openrouter": ("OPENROUTER_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "nous": ("NOUS_API_KEY",),
    "zai": ("GLM_API_KEY",),
    "kimi-coding": ("KIMI_API_KEY",),
    "moonshot": ("MOONSHOT_API_KEY",),
    "minimax": ("MINIMAX_API_KEY",),
    "minimax-cn": ("MINIMAX_CN_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "huggingface": ("HF_TOKEN",),
    "copilot": ("GITHUB_TOKEN",),
}


def _resolve_hermes_home() -> Path:
    """Resolve the Hermes home directory."""
    explicit = os.environ.get("HERMES_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".hermes"


def _resolve_config_path() -> Path:
    """Resolve the Hermes config file path."""
    explicit = os.environ.get("HERMES_CONFIG_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return _resolve_hermes_home() / "config.yaml"


def _load_hermes_config() -> Optional[Dict[str, Any]]:
    """Load and parse Hermes config.yaml. Returns None on failure."""
    config_path = _resolve_config_path()
    if not config_path.is_file():
        return None
    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML not installed, cannot read Hermes config")
        return None
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("Failed to read Hermes config %s: %s", config_path, e)
        return None


def is_hermes_host() -> bool:
    """Check if Hermes Agent is installed (config file exists)."""
    return _resolve_config_path().is_file()


def read_hermes_mcp_env(server_name: str = "openspace") -> Dict[str, str]:
    """Read the env block from a Hermes MCP server config entry.

    Looks for ``mcp_servers.<server_name>.env`` in config.yaml.
    Returns an empty dict if not found.
    """
    config = _load_hermes_config()
    if not config:
        return {}
    mcp_servers = config.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        return {}
    server = mcp_servers.get(server_name, {})
    if not isinstance(server, dict):
        return {}
    env = server.get("env", {})
    return dict(env) if isinstance(env, dict) else {}


def try_read_hermes_config(model: str = "") -> Optional[Dict[str, Any]]:
    """Try to read LLM credentials from Hermes config.

    Extracts provider, model, api_key, and api_base from the Hermes
    ``model`` config section and maps them to litellm kwargs.

    Returns None if Hermes is not installed or config is unreadable.
    """
    config = _load_hermes_config()
    if not config:
        return None

    model_cfg = config.get("model", {})
    if not isinstance(model_cfg, dict):
        return None

    result: Dict[str, Any] = {}

    # Extract provider
    provider = model_cfg.get("provider", "auto")

    # Extract model name
    hermes_model = model_cfg.get("default") or model_cfg.get("model", "")
    if hermes_model and not model:
        result["_model"] = str(hermes_model)

    # Extract API key — check config first, then env vars for the provider
    api_key = model_cfg.get("api_key", "")
    if not api_key and provider in _HERMES_PROVIDER_ENV_KEYS:
        for env_name in _HERMES_PROVIDER_ENV_KEYS[provider]:
            api_key = os.environ.get(env_name, "").strip()
            if api_key:
                break

    if api_key:
        result["api_key"] = api_key

    # Extract API base URL
    base_url = model_cfg.get("base_url", "")
    if base_url:
        result["api_base"] = str(base_url)

    # Map provider to forced_provider for gateway prefix prepending
    _GATEWAY_PROVIDERS = {"openrouter", "aihubmix", "siliconflow"}
    if provider in _GATEWAY_PROVIDERS:
        result["_forced_provider"] = provider

    if result:
        logger.info("Hermes config resolved: provider=%s, model=%s", provider, hermes_model)
        return result

    return None


def get_hermes_openai_api_key() -> Optional[str]:
    """Get OpenAI API key from Hermes config or env for embedding generation."""
    # Check env first (Hermes stores keys in .env)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key

    # Try reading from Hermes MCP server env block
    env = read_hermes_mcp_env("openspace")
    return env.get("OPENAI_API_KEY") or None
