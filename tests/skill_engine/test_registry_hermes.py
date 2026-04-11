"""Tests for SkillMeta tags/metadata and _parse_skill."""

from __future__ import annotations
import textwrap
from pathlib import Path
import pytest
from openspace.skill_engine.registry import SkillMeta, SkillRegistry


class TestSkillMeta:

    def test_defaults(self):
        meta = SkillMeta(skill_id="id1", name="test", description="desc", path=Path("/x"))
        assert meta.tags is None
        assert meta.metadata == {}

    def test_with_tags(self):
        meta = SkillMeta(skill_id="id1", name="test", description="desc", path=Path("/x"), tags=["a", "b"])
        assert meta.tags == ["a", "b"]

    def test_with_metadata(self):
        meta = SkillMeta(skill_id="id1", name="test", description="desc", path=Path("/x"), metadata={"version": "1.0"})
        assert meta.metadata["version"] == "1.0"


class TestParseSkillMd:

    def _make_skill_dir(self, tmp_path: Path, frontmatter: str):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(frontmatter, encoding="utf-8")
        return skill_dir, skill_file

    def test_parse_with_tags_list(self, tmp_path: Path):
        content = textwrap.dedent("""\
            ---
            name: my-skill
            description: A test skill
            tags: [web, api, hermes]
            ---
            Body content here.
        """)
        skill_dir, skill_file = self._make_skill_dir(tmp_path, content)
        meta = SkillRegistry._parse_skill("my-skill", skill_dir, skill_file, content)
        assert meta.tags == ["web", "api", "hermes"]

    def test_parse_without_optional_fields(self, tmp_path: Path):
        content = textwrap.dedent("""\
            ---
            name: basic-skill
            description: No extras
            ---
            Body.
        """)
        skill_dir, skill_file = self._make_skill_dir(tmp_path, content)
        meta = SkillRegistry._parse_skill("basic-skill", skill_dir, skill_file, content)
        assert meta.tags is None
        assert meta.metadata == {}
