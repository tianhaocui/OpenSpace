"""Tests for MCP server tool registration and cloud/search helpers."""

from __future__ import annotations
from openspace.cloud.search import _tokenize, _lexical_boost, _check_safety, _is_safe


class TestMcpServerTools:

    def test_four_tools_registered(self):
        from openspace.mcp_server import mcp
        tool_names = {t.name for t in mcp._tool_manager._tools.values()}
        assert "execute_task" in tool_names
        assert "search_skills" in tool_names
        assert "fix_skill" in tool_names
        assert "sync_skills_git" in tool_names
        assert len(tool_names) == 4


class TestSearchHelpers:

    def test_tokenize(self):
        tokens = _tokenize("Hello World 123")
        assert "hello" in tokens
        assert "world" in tokens
        assert "123" in tokens

    def test_lexical_boost_exact_name(self):
        boost = _lexical_boost(["git", "commit"], "git-commit", "git-commit")
        assert boost > 0

    def test_lexical_boost_no_match(self):
        boost = _lexical_boost(["python"], "git-commit", "git-commit")
        assert boost == 0.0

    def test_check_safety_delegates(self):
        flags = _check_safety("ClawdAuthenticatorTool")
        assert "blocked.malware" in flags

    def test_is_safe_delegates(self):
        assert _is_safe([]) is True
        assert _is_safe(["blocked.malware"]) is False
