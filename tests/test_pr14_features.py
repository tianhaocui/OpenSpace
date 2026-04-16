"""Tests for PR #14: auto-detect model, dashboard strip, auto-push, host skill."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# 1. Auto-detect LLM model from API keys
# ---------------------------------------------------------------------------

class TestAutoDetectModel:

    def test_anthropic_key_detects_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENSPACE_LLM_API_BASE", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        from openspace.host_detection.resolver import build_llm_kwargs
        model, _ = build_llm_kwargs("")
        assert "anthropic" in model
        assert "claude" in model

    def test_openai_key_detects_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENSPACE_LLM_API_BASE", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        from openspace.host_detection.resolver import build_llm_kwargs
        model, _ = build_llm_kwargs("")
        assert "openai" in model or "gpt" in model

    def test_explicit_model_not_overridden(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        from openspace.host_detection.resolver import build_llm_kwargs
        model, _ = build_llm_kwargs("custom/my-model")
        assert model == "custom/my-model"


# ---------------------------------------------------------------------------
# 2. OpenSpaceConfig auto-detect
# ---------------------------------------------------------------------------

class TestOpenSpaceConfigAutoDetect:

    def test_empty_model_auto_detects(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.delenv("OPENSPACE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from openspace.tool_layer import OpenSpaceConfig
        config = OpenSpaceConfig(llm_model="")
        assert config.llm_model != ""
        assert "anthropic" in config.llm_model

    def test_raises_when_no_keys(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENSPACE_LLM_API_BASE", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENSPACE_HOST", raising=False)
        from openspace.tool_layer import OpenSpaceConfig
        with pytest.raises(ValueError, match="llm_model is required"):
            OpenSpaceConfig(llm_model="")


# ---------------------------------------------------------------------------
# 3. Dashboard skills list strips heavy fields
# ---------------------------------------------------------------------------

class TestDashboardStripHeavyFields:

    def test_serialize_skill_strips_content_diff(self):
        from openspace.dashboard_server import _serialize_skill
        from openspace.skill_engine.types import SkillRecord, SkillLineage, SkillOrigin

        record = SkillRecord(
            skill_id="test-id",
            name="test-skill",
            description="test",
            path="/tmp/test/SKILL.md",
            lineage=SkillLineage(
                origin=SkillOrigin.IMPORTED,
                content_diff="huge diff content here",
                content_snapshot={"SKILL.md": "huge content"},
            ),
        )
        payload = _serialize_skill(record, include_recent_analyses=False)
        lineage = payload.get("lineage", {})
        assert "content_diff" not in lineage
        assert "content_snapshot" not in lineage

    def test_serialize_skill_keeps_fields_for_detail(self):
        from openspace.dashboard_server import _serialize_skill
        from openspace.skill_engine.types import SkillRecord, SkillLineage, SkillOrigin

        record = SkillRecord(
            skill_id="test-id",
            name="test-skill",
            description="test",
            path="/tmp/test/SKILL.md",
            lineage=SkillLineage(
                origin=SkillOrigin.IMPORTED,
                content_diff="diff",
                content_snapshot={"SKILL.md": "content"},
            ),
        )
        payload = _serialize_skill(record, include_recent_analyses=True)
        lineage = payload.get("lineage", {})
        assert "content_diff" in lineage


# ---------------------------------------------------------------------------
# 4. Evolver auto-push after evolution
# ---------------------------------------------------------------------------

class TestEvolverAutoPush:

    def test_auto_push_method_exists(self):
        from openspace.skill_engine.evolver import SkillEvolver
        assert hasattr(SkillEvolver, "_auto_push_evolved")
        import inspect
        assert inspect.iscoroutinefunction(SkillEvolver._auto_push_evolved)


# ---------------------------------------------------------------------------
# 5. Host skill exists and is valid
# ---------------------------------------------------------------------------

class TestSkillEvolutionHostSkill:

    def test_skill_md_exists(self):
        skill_path = Path(__file__).resolve().parents[1] / "openspace" / "host_skills" / "skill-evolution" / "SKILL.md"
        assert skill_path.exists()

    def test_skill_md_has_frontmatter(self):
        skill_path = Path(__file__).resolve().parents[1] / "openspace" / "host_skills" / "skill-evolution" / "SKILL.md"
        content = skill_path.read_text()
        assert content.startswith("---")
        assert "name: skill-evolution" in content
        assert "description:" in content
