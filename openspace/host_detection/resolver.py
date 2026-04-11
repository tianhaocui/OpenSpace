"""LLM credential and grounding config resolution.

Resolves the model name and litellm kwargs for OpenSpace's LLM client,
and assembles grounding config from env-var overrides.

All credentials come from environment variables (set by the AI tool
via .mcp.json env, or from openspace/.env).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("openspace.host_detection")

_PROVIDER_NATIVE_ENV_VARS: Dict[str, tuple[str, ...]] = {
    "openrouter": ("OPENROUTER_API_KEY", "OR_API_KEY"),
    "aihubmix": ("AIHUBMIX_API_KEY",),
    "siliconflow": ("SILICONFLOW_API_KEY",),
    "volcengine": ("VOLCENGINE_API_KEY", "ARK_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "zhipu": ("ZHIPU_API_KEY",),
    "dashscope": ("DASHSCOPE_API_KEY",),
    "moonshot": ("MOONSHOT_API_KEY",),
    "minimax": ("MINIMAX_API_KEY",),
    "groq": ("GROQ_API_KEY",),
}

# Provider keywords for model name → provider inference
_PROVIDER_KEYWORDS: Dict[str, tuple[str, ...]] = {
    "openrouter": ("openrouter",),
    "aihubmix": ("aihubmix",),
    "siliconflow": ("siliconflow",),
    "volcengine": ("volcengine", "volces", "ark"),
    "anthropic": ("anthropic", "claude"),
    "openai": ("openai", "gpt"),
    "deepseek": ("deepseek",),
    "gemini": ("gemini",),
    "zhipu": ("zhipu", "glm", "zai"),
    "dashscope": ("qwen", "dashscope"),
    "moonshot": ("moonshot", "kimi"),
    "minimax": ("minimax",),
    "groq": ("groq",),
}

_env_loaded = False


def _load_env_once() -> None:
    """Load .env files once per process.

    Search order (first-loaded wins for each key):
      1. ``openspace/.env``  (package root)
      2. ``CWD/.env``        (project-level fallback)
    """
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    pkg_env = Path(__file__).resolve().parent.parent / ".env"
    if pkg_env.is_file():
        load_dotenv(pkg_env)
    load_dotenv()


def load_runtime_env() -> None:
    """Public wrapper for one-time runtime .env loading."""
    _load_env_once()


def _pick_first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _ensure_local_no_proxy() -> None:
    required_hosts = ("127.0.0.1", "localhost")
    for env_name in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(env_name, "")
        entries = [entry.strip() for entry in current.split(",") if entry.strip()]
        updated = False
        for host in required_hosts:
            if host not in entries:
                entries.append(host)
                updated = True
        if updated:
            os.environ[env_name] = ",".join(entries)


def _infer_provider_name(model: str) -> Optional[str]:
    """Infer the provider name from a model string."""
    model_lower = (model or "").lower()
    model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
    normalized_prefix = model_prefix.replace("-", "_")

    # Prefix match (e.g. "anthropic/claude-sonnet-4.5" → "anthropic")
    if model_prefix and normalized_prefix in _PROVIDER_NATIVE_ENV_VARS:
        return normalized_prefix

    # Keyword match
    for name, keywords in _PROVIDER_KEYWORDS.items():
        if any(kw in model_lower for kw in keywords):
            return name

    return None


def _has_provider_native_env(model: str) -> bool:
    """Check if a provider-native API key exists in the environment."""
    provider = _infer_provider_name(model)
    if not provider:
        return False
    env_names = _PROVIDER_NATIVE_ENV_VARS.get(provider)
    if not env_names:
        return False
    return bool(_pick_first_env(env_names))


def build_llm_kwargs(model: str) -> tuple[str, Dict[str, Any]]:
    """Build litellm kwargs and resolve model for OpenSpace's LLM client.

    Resolution order (highest → lowest priority):

    Tier 1 — Explicit ``OPENSPACE_LLM_*`` env vars::

        OPENSPACE_LLM_API_KEY         → litellm ``api_key``
        OPENSPACE_LLM_API_BASE        → litellm ``api_base``
        OPENSPACE_LLM_EXTRA_HEADERS   → litellm ``extra_headers`` (JSON string)
        OPENSPACE_LLM_CONFIG          → arbitrary litellm kwargs (JSON string)

    Tier 2 — Provider-native env vars (set by the AI tool via .mcp.json
    env, or loaded from ``openspace/.env``)::

        OPENROUTER_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / ...

    Returns:
        ``(resolved_model, llm_kwargs_dict)``
    """
    _load_env_once()

    kwargs: Dict[str, Any] = {}
    resolved_model = model
    source = "inherited env"

    # --- Tier 1: explicit env vars ---
    api_key = os.environ.get("OPENSPACE_LLM_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
        source = "OPENSPACE_LLM_* env"

    api_base = os.environ.get("OPENSPACE_LLM_API_BASE")
    if api_base:
        kwargs["api_base"] = api_base

    extra_headers_raw = os.environ.get("OPENSPACE_LLM_EXTRA_HEADERS")
    if extra_headers_raw:
        try:
            headers = json.loads(extra_headers_raw)
            if isinstance(headers, dict):
                kwargs["extra_headers"] = headers
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in OPENSPACE_LLM_EXTRA_HEADERS: %r", extra_headers_raw)

    llm_config_raw = os.environ.get("OPENSPACE_LLM_CONFIG")
    if llm_config_raw:
        try:
            llm_config = json.loads(llm_config_raw)
            if isinstance(llm_config, dict):
                kwargs.update(llm_config)
                source = "OPENSPACE_LLM_CONFIG env"
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in OPENSPACE_LLM_CONFIG: %r", llm_config_raw)

    # Model from env
    if not resolved_model:
        resolved_model = os.environ.get("OPENSPACE_MODEL", "").strip()

    # Warn if no model configured
    if not resolved_model:
        logger.warning(
            "No LLM model configured. Set OPENSPACE_MODEL or pass model via "
            "the AI tool's .mcp.json env."
        )

    # Ollama special handling
    if resolved_model and resolved_model.lower().startswith("ollama/"):
        ollama_base = os.environ.get("OLLAMA_API_BASE", "").strip() or "http://127.0.0.1:11434"
        _ensure_local_no_proxy()
        kwargs["api_base"] = ollama_base.rstrip("/")
        kwargs["api_key"] = os.environ.get("OLLAMA_API_KEY", "").strip() or kwargs.get("api_key") or "ollama"
        kwargs.pop("extra_headers", None)
        source = "ollama runtime"

    # MiniMax compat
    if resolved_model and "minimax" in resolved_model.lower():
        final_key = kwargs.get("api_key")
        final_base = kwargs.get("api_base", "")
        if final_key:
            os.environ.setdefault("MINIMAX_API_KEY", final_key)
        if final_base:
            os.environ.setdefault("MINIMAX_API_BASE", final_base)
        if resolved_model.lower().startswith("minimax/") and "minimaxi.com" in final_base:
            original = resolved_model
            resolved_model = "openai/" + resolved_model.split("/", 1)[1]
            logger.info("Switched model prefix for minimaxi.com compat: %s -> %s", original, resolved_model)

    if kwargs:
        safe = {
            k: (v[:8] + "..." if k == "api_key" and isinstance(v, str) and len(v) > 8 else v)
            for k, v in kwargs.items()
        }
        logger.info("LLM kwargs resolved (source=%s): %s", source, safe)
    elif _has_provider_native_env(resolved_model or ""):
        logger.info("LLM credentials resolved from provider-native env for model=%r", resolved_model)

    return resolved_model, kwargs

def build_grounding_config_path() -> Optional[str]:
    """Resolve grounding config: inline JSON > file path > None.

    Supports:
      * ``OPENSPACE_CONFIG_JSON``  — inline JSON string (written to a temp file)
      * ``OPENSPACE_CONFIG_PATH``  — path to a JSON config file

    Returns:
        Path to the resolved config file, or None.
    """
    _load_env_once()

    config_json_raw = os.environ.get("OPENSPACE_CONFIG_JSON", "").strip()
    overrides: Dict[str, Any] = {}
    if config_json_raw:
        try:
            overrides = json.loads(config_json_raw)
            if not isinstance(overrides, dict):
                logger.warning("OPENSPACE_CONFIG_JSON is not a dict, ignoring")
                overrides = {}
            else:
                logger.info("Loaded inline config from OPENSPACE_CONFIG_JSON")
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in OPENSPACE_CONFIG_JSON: %s", e)

    # --- Granular env-var overrides ---
    conda_env = os.environ.get("OPENSPACE_SHELL_CONDA_ENV", "").strip()
    if conda_env:
        overrides.setdefault("shell", {})["conda_env"] = conda_env

    shell_wd = os.environ.get("OPENSPACE_SHELL_WORKING_DIR", "").strip()
    if shell_wd:
        overrides.setdefault("shell", {})["working_dir"] = shell_wd

    skills_dirs_raw = os.environ.get("OPENSPACE_SKILLS_DIRS", "").strip()
    if skills_dirs_raw:
        dirs = [d.strip() for d in skills_dirs_raw.split(",") if d.strip()]
        if dirs:
            overrides.setdefault("skills", {})["skill_dirs"] = dirs

    mcp_servers_raw = os.environ.get("OPENSPACE_MCP_SERVERS_JSON", "").strip()
    if mcp_servers_raw:
        try:
            servers = json.loads(mcp_servers_raw)
            if isinstance(servers, dict):
                overrides["mcpServers"] = servers
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in OPENSPACE_MCP_SERVERS_JSON: %s", e)

    log_level = os.environ.get("OPENSPACE_LOG_LEVEL", "").strip().upper()
    if log_level and log_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        overrides["log_level"] = log_level

    if overrides:
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="openspace_cfg_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(overrides, f, ensure_ascii=False)
            logger.info(
                "Grounding config overrides written to %s (%d keys)",
                tmp_path, len(overrides),
            )
            return tmp_path
        except Exception as e:
            logger.warning("Failed to write config overrides: %s", e)

    return os.environ.get("OPENSPACE_CONFIG_PATH")
