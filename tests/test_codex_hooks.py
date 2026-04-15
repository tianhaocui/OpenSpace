#!/usr/bin/env python3
"""Stop hook integration — unit tests for Codex + Claude Code transcript parsing."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from openspace.codex_hooks.stop_hook import (
    _check_manual_reports,
    _detect_format,
    _extract_assistant_skill_refs,
    _extract_loaded_skills,
    _extract_skill_evaluations,
    _load_transcript,
)


# ── Codex format helpers ──

def _codex_developer_msg(text: str) -> dict:
    return {
        "type": "response_item",
        "payload": {
            "role": "developer",
            "type": "message",
            "content": [{"type": "input_text", "text": text}],
        },
    }


def _codex_assistant_msg(text: str) -> dict:
    return {
        "type": "response_item",
        "payload": {
            "role": "assistant",
            "type": "message",
            "content": [{"type": "output_text", "text": text}],
        },
    }


def _codex_function_call(name: str, arguments: dict) -> dict:
    return {
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


# ── Claude Code format helpers ──

def _claude_user_msg(text: str) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


def _claude_assistant_msg(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _claude_tool_use(name: str, input_data: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": input_data}],
        },
    }


class TestDetectFormat:
    def test_detects_codex(self):
        entries = [_codex_developer_msg("hello")]
        assert _detect_format(entries) == "codex"

    def test_detects_claude(self):
        entries = [_claude_user_msg("hello")]
        assert _detect_format(entries) == "claude"

    def test_unknown_for_empty(self):
        assert _detect_format([]) == "unknown"


class TestExtractLoadedSkillsCodex:
    def test_extracts_skills_from_developer_message(self):
        entries = [
            _codex_developer_msg(
                "Available skills:\n"
                "- git-commit (file: /root/.agents/skills/git-commit/SKILL.md)\n"
                "- lark-docs (file: /root/.codex/skills/lark-docs/SKILL.md)\n"
            ),
        ]
        result = _extract_loaded_skills(entries)
        assert result == {"git-commit", "lark-docs"}

    def test_ignores_system_skills(self):
        entries = [
            _codex_developer_msg(
                "- imagegen (file: /root/.codex/skills/.system/imagegen/SKILL.md)\n"
                "- openai-docs (file: /root/.codex/skills/.system/openai-docs/SKILL.md)\n"
                "- git-commit (file: /root/.agents/skills/git-commit/SKILL.md)\n"
            ),
        ]
        result = _extract_loaded_skills(entries)
        assert result == {"git-commit"}

    def test_ignores_dot_prefixed_skills(self):
        entries = [
            _codex_developer_msg(
                "- .system (file: /root/.codex/skills/.system/SKILL.md)\n"
            ),
        ]
        result = _extract_loaded_skills(entries)
        assert result == set()

    def test_empty_entries(self):
        assert _extract_loaded_skills([]) == set()


class TestExtractLoadedSkillsClaude:
    def test_extracts_skills_from_user_message(self):
        entries = [
            _claude_user_msg(
                "<system-reminder>\n"
                "- git-commit (file: /root/.claude/skills/git-commit/SKILL.md)\n"
                "- lark-docs (file: /root/.agents/skills/lark-docs/SKILL.md)\n"
                "</system-reminder>"
            ),
        ]
        result = _extract_loaded_skills(entries, fmt="claude")
        assert result == {"git-commit", "lark-docs"}

    def test_extracts_skills_from_dash_list_format(self):
        entries = [
            _claude_user_msg(
                "<system-reminder>\n"
                "The following skills are available for use with the Skill tool:\n\n"
                "- git-commit: Execute git commit with conventional messages\n"
                "- lark-docs: Read and write Feishu documents\n"
                "- skill-evolution: Auto-evolve skills after use\n"
                "</system-reminder>"
            ),
        ]
        result = _extract_loaded_skills(entries, fmt="claude")
        assert result == {"git-commit", "lark-docs", "skill-evolution"}

    def test_ignores_system_skills(self):
        entries = [
            _claude_user_msg(
                "- imagegen (file: /root/.codex/skills/.system/imagegen/SKILL.md)\n"
                "- git-commit (file: /root/.agents/skills/git-commit/SKILL.md)\n"
            ),
        ]
        result = _extract_loaded_skills(entries, fmt="claude")
        assert result == {"git-commit"}


class TestExtractAssistantSkillRefsCodex:
    def test_finds_referenced_skills(self):
        loaded = {"git-commit", "lark-docs", "prd"}
        entries = [
            _codex_assistant_msg("I'll use the git-commit skill to commit your changes."),
            _codex_assistant_msg("Let me check the prd for requirements."),
        ]
        result = _extract_assistant_skill_refs(entries, loaded)
        assert result == {"git-commit", "prd"}

    def test_unreferenced_skills_excluded(self):
        loaded = {"git-commit", "lark-docs"}
        entries = [
            _codex_assistant_msg("Done! Your code is committed."),
        ]
        result = _extract_assistant_skill_refs(entries, loaded)
        assert result == set()


class TestExtractAssistantSkillRefsClaude:
    def test_finds_referenced_skills(self):
        loaded = {"git-commit", "lark-docs", "prd"}
        entries = [
            _claude_assistant_msg("I'll use the git-commit skill to commit."),
            _claude_assistant_msg("Checking the prd now."),
        ]
        result = _extract_assistant_skill_refs(entries, loaded, fmt="claude")
        assert result == {"git-commit", "prd"}

    def test_unreferenced_skills_excluded(self):
        loaded = {"git-commit", "lark-docs"}
        entries = [
            _claude_assistant_msg("Done! Your code is committed."),
        ]
        result = _extract_assistant_skill_refs(entries, loaded, fmt="claude")
        assert result == set()


class TestCheckManualReportsCodex:
    def test_detects_report_skill_usage_calls(self):
        entries = [
            _codex_function_call(
                "report_skill_usage",
                {"skill_name": "git-commit", "task_completed": True},
            ),
        ]
        result = _check_manual_reports(entries)
        assert result == {"git-commit"}

    def test_detects_fix_skill_calls(self):
        entries = [
            _codex_function_call(
                "fix_skill",
                {"skill_name": "lark-docs", "direction": "update API endpoint"},
            ),
        ]
        result = _check_manual_reports(entries)
        assert result == {"lark-docs"}

    def test_ignores_other_tool_calls(self):
        entries = [
            _codex_function_call("exec_command", {"command": "ls"}),
        ]
        result = _check_manual_reports(entries)
        assert result == set()


class TestCheckManualReportsClaude:
    def test_detects_report_skill_usage_calls(self):
        entries = [
            _claude_tool_use(
                "report_skill_usage",
                {"skill_name": "git-commit", "task_completed": True},
            ),
        ]
        result = _check_manual_reports(entries, fmt="claude")
        assert result == {"git-commit"}

    def test_detects_fix_skill_calls(self):
        entries = [
            _claude_tool_use(
                "fix_skill",
                {"skill_name": "lark-docs", "direction": "update endpoint"},
            ),
        ]
        result = _check_manual_reports(entries, fmt="claude")
        assert result == {"lark-docs"}

    def test_ignores_other_tool_calls(self):
        entries = [
            _claude_tool_use("Bash", {"command": "ls"}),
        ]
        result = _check_manual_reports(entries, fmt="claude")
        assert result == set()


class TestLoadTranscript:
    def test_loads_jsonl_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "session_meta"}) + "\n")
            f.write(json.dumps({"type": "response_item", "payload": {}}) + "\n")
            f.flush()
            result = _load_transcript(f.name)
        assert len(result) == 2
        Path(f.name).unlink()

    def test_returns_empty_for_missing_file(self):
        assert _load_transcript("/nonexistent/path.jsonl") == []

    def test_returns_empty_for_none(self):
        assert _load_transcript(None) == []


class TestExtractSkillEvaluationsCodex:
    def test_extracts_evaluations(self):
        entries = [
            _codex_assistant_msg(
                "[A] skillpull — accurate and complete, no changes needed\n"
                "[B] git-commit — missing amend example → evolving\n"
                "[C] lark-docs — wrong API endpoint → evolving\n"
                "[F] old-workflow — completely outdated → flagged for review\n"
            ),
        ]
        result = _extract_skill_evaluations(entries, fmt="codex")
        assert result["skillpull"] == ("A", "accurate and complete, no changes needed")
        assert result["git-commit"] == ("B", "missing amend example → evolving")
        assert result["lark-docs"] == ("C", "wrong API endpoint → evolving")
        assert result["old-workflow"] == ("F", "completely outdated → flagged for review")

    def test_no_evaluations(self):
        entries = [
            _codex_assistant_msg("Done! Your code is committed."),
        ]
        result = _extract_skill_evaluations(entries, fmt="codex")
        assert result == {}

    def test_last_evaluation_wins(self):
        entries = [
            _codex_assistant_msg("[B] git-commit — first issue"),
            _codex_assistant_msg("[C] git-commit — worse issue found later"),
        ]
        result = _extract_skill_evaluations(entries, fmt="codex")
        assert result["git-commit"] == ("C", "worse issue found later")


class TestExtractSkillEvaluationsClaude:
    def test_extracts_evaluations(self):
        entries = [
            _claude_assistant_msg(
                "[A] skillpull — accurate and complete\n"
                "[B] lark-docs — missing auth step\n"
            ),
        ]
        result = _extract_skill_evaluations(entries, fmt="claude")
        assert result["skillpull"] == ("A", "accurate and complete")
        assert result["lark-docs"] == ("B", "missing auth step")

    def test_em_dash_and_en_dash(self):
        entries = [
            _claude_assistant_msg(
                "[B] skill-a — em dash reason\n"
                "[C] skill-b – en dash reason\n"
                "[F] skill-c - hyphen reason\n"
            ),
        ]
        result = _extract_skill_evaluations(entries, fmt="claude")
        assert len(result) == 3
        assert result["skill-a"][0] == "B"
        assert result["skill-b"][0] == "C"
        assert result["skill-c"][0] == "F"
