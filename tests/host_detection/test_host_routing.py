"""Tests for host_detection __init__.py — auto-detection chain."""

from __future__ import annotations
from unittest import mock
import pytest

_NANOBOT_MCP = "openspace.host_detection.read_nanobot_mcp_env"
_OPENCLAW_MCP = "openspace.host_detection.read_openclaw_skill_env"
_NANOBOT_OAI = "openspace.host_detection._nanobot_get_openai_api_key"
_OPENCLAW_OAI = "openspace.host_detection._openclaw_get_openai_api_key"


class TestReadHostMcpEnvAutoDetect:

    def test_nanobot_wins(self):
        with mock.patch(_NANOBOT_MCP, return_value={"FROM": "nano"}), \
             mock.patch(_OPENCLAW_MCP, return_value={"FROM": "claw"}):
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env()["FROM"] == "nano"

    def test_openclaw_when_nanobot_empty(self):
        with mock.patch(_NANOBOT_MCP, return_value={}), \
             mock.patch(_OPENCLAW_MCP, return_value={"FROM": "claw"}):
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env()["FROM"] == "claw"

    def test_empty_when_all_empty(self):
        with mock.patch(_NANOBOT_MCP, return_value={}), \
             mock.patch(_OPENCLAW_MCP, return_value={}):
            from openspace.host_detection import read_host_mcp_env
            assert read_host_mcp_env() == {}


class TestGetOpenaiApiKeyAutoDetect:

    def test_nanobot_key(self):
        with mock.patch(_NANOBOT_OAI, return_value="sk-nano"):
            from openspace.host_detection import get_openai_api_key
            assert get_openai_api_key() == "sk-nano"

    def test_openclaw_fallback(self):
        with mock.patch(_NANOBOT_OAI, return_value=None), \
             mock.patch(_OPENCLAW_OAI, return_value="sk-claw"):
            from openspace.host_detection import get_openai_api_key
            assert get_openai_api_key() == "sk-claw"

    def test_none_when_all_empty(self):
        with mock.patch(_NANOBOT_OAI, return_value=None), \
             mock.patch(_OPENCLAW_OAI, return_value=None):
            from openspace.host_detection import get_openai_api_key
            assert get_openai_api_key() is None
