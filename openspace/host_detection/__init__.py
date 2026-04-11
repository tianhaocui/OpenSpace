"""Host-agent config auto-detection.

Public API consumed by other OpenSpace subsystems (cloud, mcp_server, …):

  - ``build_llm_kwargs``          — resolve LLM credentials
  - ``build_grounding_config_path`` — resolve grounding config
  - ``load_runtime_env``          — one-time .env loading
  - ``read_host_mcp_env``         — host-agnostic skill env reader
  - ``get_openai_api_key``        — OpenAI key resolution (multi-host)

Internal / legacy re-exports (prefer the generic names above):

  - ``read_nanobot_mcp_env``      — nanobot-specific, kept for backward compat
  - ``try_read_nanobot_config``

Supported host agents:

  - **nanobot** — ``~/.nanobot/config.json``  (``tools.mcpServers.openspace.env``)
  - **openclaw** — ``~/.openclaw/openclaw.json``  (``skills.entries.openspace.env``)
  - **hermes** — ``~/.hermes/config.yaml``  (``mcp_servers.openspace.env``)
"""

import logging
import os
from typing import Dict, Optional

from openspace.host_detection.resolver import (
    build_llm_kwargs,
    build_grounding_config_path,
    load_runtime_env,
)
from openspace.host_detection.nanobot import (
    get_openai_api_key as _nanobot_get_openai_api_key,
    read_nanobot_mcp_env,
    try_read_nanobot_config,
)
from openspace.host_detection.openclaw import (
    get_openclaw_openai_api_key as _openclaw_get_openai_api_key,
    is_openclaw_host,
    read_openclaw_skill_env,
)
from openspace.host_detection.hermes import (
    read_hermes_mcp_env,
    get_hermes_openai_api_key as _hermes_get_openai_api_key,
    is_hermes_host,
)

logger = logging.getLogger("openspace.host_detection")


def read_host_mcp_env() -> Dict[str, str]:
    """Read the OpenSpace env block from the current host agent config.

    Resolution order:
      0. ``OPENSPACE_HOST`` env var — explicit routing (nanobot / openclaw / hermes)
      1. nanobot — ``tools.mcpServers.openspace.env``
      2. openclaw — ``skills.entries.openspace.env``
      3. hermes — Hermes config
      4. Empty dict (no host detected)
    """
    explicit = os.environ.get("OPENSPACE_HOST", "").strip().lower()
    if explicit:
        if explicit == "nanobot":
            return read_nanobot_mcp_env()
        elif explicit == "openclaw":
            return read_openclaw_skill_env("openspace")
        elif explicit == "hermes":
            return read_hermes_mcp_env("openspace")
        else:
            logger.warning("Unknown OPENSPACE_HOST=%r, falling through to auto-detection", explicit)

    # Auto-detection chain: nanobot → openclaw → hermes → empty
    env = read_nanobot_mcp_env()
    if env:
        return env

    env = read_openclaw_skill_env("openspace")
    if env:
        logger.debug("read_host_mcp_env: resolved from OpenClaw config")
        return env

    env = read_hermes_mcp_env("openspace")
    if env:
        logger.debug("read_host_mcp_env: resolved from Hermes config")
        return env

    return {}


def get_openai_api_key() -> Optional[str]:
    """Get OpenAI API key for embedding generation (multi-host).

    Resolution:
      0. ``OPENSPACE_HOST`` env var — explicit routing
      1. nanobot config
      2. openclaw config
      3. hermes config
      4. None
    """
    explicit = os.environ.get("OPENSPACE_HOST", "").strip().lower()
    if explicit:
        if explicit == "nanobot":
            return _nanobot_get_openai_api_key()
        elif explicit == "openclaw":
            return _openclaw_get_openai_api_key()
        elif explicit == "hermes":
            return _hermes_get_openai_api_key()

    key = _nanobot_get_openai_api_key()
    if key:
        return key
    key = _openclaw_get_openai_api_key()
    if key:
        return key
    return _hermes_get_openai_api_key()


__all__ = [
    "build_llm_kwargs",
    "build_grounding_config_path",
    "load_runtime_env",
    "get_openai_api_key",
    "read_host_mcp_env",
    # legacy re-exports
    "read_nanobot_mcp_env",
    "try_read_nanobot_config",
    # openclaw-specific
    "is_openclaw_host",
    "read_openclaw_skill_env",
    # hermes
    "is_hermes_host",
    "read_hermes_mcp_env",
]
