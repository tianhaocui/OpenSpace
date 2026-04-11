"""Tests for privatization: cloud toggle, MCP tools, telemetry defaults."""

from __future__ import annotations

from unittest import mock

import pytest

from openspace.cloud.auth import is_cloud_enabled, get_openspace_auth


class TestCloudToggle:

    def test_disabled_by_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_CLOUD_ENABLED", "false")
        assert is_cloud_enabled() is False

    def test_disabled_by_zero(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_CLOUD_ENABLED", "0")
        assert is_cloud_enabled() is False

    def test_enabled_by_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_CLOUD_ENABLED", raising=False)
        assert is_cloud_enabled() is True

    def test_enabled_explicitly(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_CLOUD_ENABLED", "true")
        assert is_cloud_enabled() is True

    def test_auth_returns_empty_when_disabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_CLOUD_ENABLED", "false")
        monkeypatch.delenv("OPENSPACE_API_KEY", raising=False)
        headers, base = get_openspace_auth()
        assert headers == {}


class TestMcpServerTools:
    """Verify MCP server exposes exactly 3 tools (no upload_skill)."""

    def test_exactly_three_tools(self):
        from openspace.mcp_server import mcp
        tool_names = set()
        # mcp.list_tools() or inspect registered tools
        for tool in mcp._tool_manager._tools.values():
            tool_names.add(tool.name)
        assert "execute_task" in tool_names
        assert "search_skills" in tool_names
        assert "fix_skill" in tool_names
        assert "upload_skill" not in tool_names
        assert len(tool_names) == 3


class TestNoHardcodedModels:
    """Verify no hardcoded OpenRouter model defaults remain."""

    def test_llm_client_no_hardcoded_default(self):
        import openspace.llm.client as client_mod
        import inspect
        source = inspect.getsource(client_mod)
        assert "openrouter/anthropic/claude-sonnet-4.5" not in source


class TestHostDetectionRemoved:
    """Verify host agent detection modules are removed."""

    def test_no_hermes_module(self):
        import importlib
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("openspace.host_detection.hermes")

    def test_no_nanobot_module(self):
        import importlib
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("openspace.host_detection.nanobot")

    def test_no_openclaw_module(self):
        import importlib
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("openspace.host_detection.openclaw")
