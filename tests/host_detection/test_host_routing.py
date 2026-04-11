"""Tests for host_detection __init__.py — OPENSPACE_HOST routing & auto-detection chain.

Verifies that adding Hermes as the third host agent doesn't break
the existing nanobot/openclaw detection, and that OPENSPACE_HOST
explicit routing works correctly.
"""

from __future__ import annotations

from unittest import mock

import pytest


# We mock the individual host readers to isolate the routing logic.
_NANOBOT_MCP = "openspace.host_detection.read_nanobot_mcp_env"
_OPENCLAW_MCP = "openspace.host_detection.read_openclaw_skill_env"
_HERMES_MCP = "openspace.host_detection.read_hermes_mcp_env"

_NANOBOT_OAI = "openspace.host_detection._nanobot_get_openai_api_key"
_OPENCLAW_OAI = "openspace.host_detection._openclaw_get_openai_api_key"
_HERMES_OAI = "openspace.host_detection._hermes_get_openai_api_key"


# ---------------------------------------------------------------------------
# read_host_mcp_env — OPENSPACE_HOST explicit routing
# ---------------------------------------------------------------------------

class TestReadHostMcpEnvExplicit:
    """OPENSPACE_HOST env var bypasses auto-detection."""

    def test_explicit_nanobot(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_HOST", "nanobot")
        with mock.patch(_NANOBOT_MCP, return_value={"K": "nano"}) as m:
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env() == {"K": "nano"}
            m.assert_called_once()

    def test_explicit_openclaw(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_HOST", "openclaw")
        with mock.patch(_OPENCLAW_MCP, return_value={"K": "claw"}) as m:
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env() == {"K": "claw"}
            m.assert_called_once_with("openspace")

    def test_explicit_hermes(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_HOST", "hermes")
        with mock.patch(_HERMES_MCP, return_value={"K": "hermes"}) as m:
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env() == {"K": "hermes"}
            m.assert_called_once_with("openspace")

    def test_unknown_host_falls_through(self, monkeypatch: pytest.MonkeyPatch):
        """Unknown OPENSPACE_HOST should log warning and fall through to auto-detection."""
        monkeypatch.setenv("OPENSPACE_HOST", "unknown_agent")
        with (
            mock.patch(_NANOBOT_MCP, return_value={}),
            mock.patch(_OPENCLAW_MCP, return_value={}),
            mock.patch(_HERMES_MCP, return_value={}),
        ):
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env() == {}


# ---------------------------------------------------------------------------
# read_host_mcp_env — auto-detection chain (no OPENSPACE_HOST)
# ---------------------------------------------------------------------------

class TestReadHostMcpEnvAutoDetect:
    """Without OPENSPACE_HOST, chain is nanobot → openclaw → hermes → empty."""

    def _clear_host(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_HOST", raising=False)

    def test_nanobot_wins(self, monkeypatch: pytest.MonkeyPatch):
        self._clear_host(monkeypatch)
        with (
            mock.patch(_NANOBOT_MCP, return_value={"FROM": "nano"}),
            mock.patch(_OPENCLAW_MCP, return_value={"FROM": "claw"}),
            mock.patch(_HERMES_MCP, return_value={"FROM": "hermes"}),
        ):
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env()["FROM"] == "nano"

    def test_openclaw_when_nanobot_empty(self, monkeypatch: pytest.MonkeyPatch):
        self._clear_host(monkeypatch)
        with (
            mock.patch(_NANOBOT_MCP, return_value={}),
            mock.patch(_OPENCLAW_MCP, return_value={"FROM": "claw"}),
            mock.patch(_HERMES_MCP, return_value={"FROM": "hermes"}),
        ):
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env()["FROM"] == "claw"

    def test_hermes_when_others_empty(self, monkeypatch: pytest.MonkeyPatch):
        self._clear_host(monkeypatch)
        with (
            mock.patch(_NANOBOT_MCP, return_value={}),
            mock.patch(_OPENCLAW_MCP, return_value={}),
            mock.patch(_HERMES_MCP, return_value={"FROM": "hermes"}),
        ):
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env()["FROM"] == "hermes"

    def test_empty_when_all_empty(self, monkeypatch: pytest.MonkeyPatch):
        self._clear_host(monkeypatch)
        with (
            mock.patch(_NANOBOT_MCP, return_value={}),
            mock.patch(_OPENCLAW_MCP, return_value={}),
            mock.patch(_HERMES_MCP, return_value={}),
        ):
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env() == {}


# ---------------------------------------------------------------------------
# get_openai_api_key — same routing patterns
# ---------------------------------------------------------------------------

class TestGetOpenaiApiKeyExplicit:

    def test_explicit_hermes(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_HOST", "hermes")
        with mock.patch(_HERMES_OAI, return_value="sk-hermes") as m:
            from openspace.host_detection import get_openai_api_key
            assert get_openai_api_key() == "sk-hermes"
            m.assert_called_once()

    def test_explicit_nanobot(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_HOST", "nanobot")
        with mock.patch(_NANOBOT_OAI, return_value="sk-nano") as m:
            from openspace.host_detection import get_openai_api_key
            assert get_openai_api_key() == "sk-nano"


class TestGetOpenaiApiKeyAutoDetect:

    def test_hermes_fallback(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_HOST", raising=False)
        with (
            mock.patch(_NANOBOT_OAI, return_value=None),
            mock.patch(_OPENCLAW_OAI, return_value=None),
            mock.patch(_HERMES_OAI, return_value="sk-hermes"),
        ):
            from openspace.host_detection import get_openai_api_key
            assert get_openai_api_key() == "sk-hermes"

    def test_none_when_all_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_HOST", raising=False)
        with (
            mock.patch(_NANOBOT_OAI, return_value=None),
            mock.patch(_OPENCLAW_OAI, return_value=None),
            mock.patch(_HERMES_OAI, return_value=None),
        ):
            from openspace.host_detection import get_openai_api_key
            assert get_openai_api_key() is None


# ---------------------------------------------------------------------------
# Compatibility: Hermes detection must not break existing hosts
# ---------------------------------------------------------------------------

class TestCrossHostCompatibility:
    """Adding Hermes must not change behavior when only nanobot/openclaw are present."""

    def test_nanobot_only_still_works(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_HOST", raising=False)
        with (
            mock.patch(_NANOBOT_MCP, return_value={"OPENSPACE_API_KEY": "nano-key"}),
            mock.patch(_OPENCLAW_MCP, return_value={}),
            mock.patch(_HERMES_MCP, return_value={}),
        ):
            from openspace.host_detection import read_host_mcp_env
            env = read_host_mcp_env()
            assert env == {"OPENSPACE_API_KEY": "nano-key"}

    def test_openclaw_only_still_works(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_HOST", raising=False)
        with (
            mock.patch(_NANOBOT_MCP, return_value={}),
            mock.patch(_OPENCLAW_MCP, return_value={"OPENSPACE_API_KEY": "claw-key"}),
            mock.patch(_HERMES_MCP, return_value={}),
        ):
            from openspace.host_detection import read_host_mcp_env
            env = read_host_mcp_env()
            assert env == {"OPENSPACE_API_KEY": "claw-key"}

