"""Tests for SkillMeta tags/metadata fields and registry parsing."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from openspace.skill_engine.registry import SkillMeta, SkillRegistry


# ---------------------------------------------------------------------------
# SkillMeta dataclass
# ---------------------------------------------------------------------------

class TestSkillMeta:

    def test_defaults(self):
        meta = SkillMeta(skill_id="id1", name="test", description="desc", path=Path("/x"))
        assert meta.tags is None
        assert meta.metadata == {}  # __post_init__ sets empty dict

    def test_with_tags(self):
        meta = SkillMeta(
            skill_id="id1", name="test", description="desc",
            path=Path("/x"), tags=["a", "b"],
        )
        assert meta.tags == ["a", "b"]

    def test_with_metadata(self):
        meta = SkillMeta(
            skill_id="id1", name="test", description="desc",
            path=Path("/x"), metadata={"version": "1.0", "author": "alice"},
        )
        assert meta.metadata["version"] == "1.0"


# ---------------------------------------------------------------------------
# SkillRegistry._parse_skill — tags & metadata extraction
# ---------------------------------------------------------------------------

class TestParseSkillMd:

    def _make_skill_dir(self, tmp_path: Path, frontmatter: str) -> tuple[Path, Path]:
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
        assert meta.name == "my-skill"
        assert meta.tags == ["web", "api", "hermes"]

    def test_parse_with_agentskills_metadata(self, tmp_path: Path):
        content = textwrap.dedent("""\
            ---
            name: hermes-skill
            description: Hermes compatible
            version: "2.0"
            author: hermes-team
            license: MIT
            platforms: [linux, macos]
            ---
            Body.
        """)
        skill_dir, skill_file = self._make_skill_dir(tmp_path, content)
        meta = SkillRegistry._parse_skill("hermes-skill", skill_dir, skill_file, content)
        assert meta.metadata.get("version") == "2.0"
        assert meta.metadata.get("author") == "hermes-team"
        assert meta.metadata.get("license") == "MIT"

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

    def test_hermes_nested_tags(self, tmp_path: Path):
        content = textwrap.dedent("""\
            ---
            name: nested-tags
            description: Tags in metadata.hermes
            metadata:
              hermes:
                tags: [agent, automation]
            ---
            Body.
        """)
        skill_dir, skill_file = self._make_skill_dir(tmp_path, content)
        meta = SkillRegistry._parse_skill("nested-tags", skill_dir, skill_file, content)
        assert meta.tags == ["agent", "automation"]
