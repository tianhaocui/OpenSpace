"""LLM credential and config resolution.

Public API:
  - ``build_llm_kwargs``           — resolve LLM credentials from env vars
  - ``build_grounding_config_path`` — resolve grounding config
  - ``load_runtime_env``           — one-time .env loading
  - ``get_openai_api_key``         — OpenAI key from env (for embeddings)

All credentials come from environment variables, set by the AI tool
(Claude Code / Codex / Kiro) via .mcp.json env or openspace/.env.
"""

import os
from typing import Optional

from openspace.host_detection.resolver import (
    build_llm_kwargs,
    build_grounding_config_path,
    load_runtime_env,
)


def get_openai_api_key() -> Optional[str]:
    """Get OpenAI API key for embedding generation.

    Reads from ``OPENAI_API_KEY`` environment variable.
    """
    return os.environ.get("OPENAI_API_KEY", "").strip() or None


def read_host_mcp_env() -> dict:
    """Stub — returns empty dict. Host agent detection removed for private deployment."""
    return {}


__all__ = [
    "build_llm_kwargs",
    "build_grounding_config_path",
    "load_runtime_env",
    "get_openai_api_key",
    "read_host_mcp_env",
]
