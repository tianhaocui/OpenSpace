"""Tests for host_detection/skill_dirs.py — multi-agent skill directory auto-discovery."""

from __future__ import annotations
from pathlib import Path
from unittest import mock
import pytest
import openspace.host_detection.skill_dirs as skill_dirs_mod
from openspace.host_detection.skill_dirs import auto_detect_skill_dirs, broadcast_evolved_skill


class TestAutoDetectSkillDirs:

    def test_disabled_by_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENSPACE_AUTO_DETECT", "false")
        assert auto_detect_skill_dirs() == []

    def test_returns_existing_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_AUTO_DETECT", raising=False)
        hub = tmp_path / ".agents" / "skills"
        hub.mkdir(parents=True)
        claude_dir = tmp_path / ".claude" / "skills"
        claude_dir.mkdir(parents=True)
        fake_dirs = [
            ("shared-hub", hub, ".agents/skills", True),
            ("claude", claude_dir, ".claude/skills", True),
            ("codex", tmp_path / ".codex" / "skills", ".codex/skills", True),
        ]
        with mock.patch.object(skill_dirs_mod, "_AGENT_DIRS", fake_dirs):
            result = auto_detect_skill_dirs()
        assert hub in result
        assert claude_dir in result
        assert tmp_path / ".codex" / "skills" not in result

    def test_deduplicates_resolved_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENSPACE_AUTO_DETECT", raising=False)
        skills = tmp_path / "skills"
        skills.mkdir()
        fake_dirs = [("a", skills, None, True), ("b", skills, None, True)]
        with mock.patch.object(skill_dirs_mod, "_AGENT_DIRS", fake_dirs):
            assert len(auto_detect_skill_dirs()) == 1


class TestBroadcastEvolvedSkill:

    def test_skips_when_no_shared_hub(self, tmp_path: Path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("name: my-skill")
        with mock.patch.object(skill_dirs_mod, "_SHARED_HUB", tmp_path / "nonexistent"):
            assert broadcast_evolved_skill(skill_dir, "my-skill") == 0

    def test_copies_to_hub_and_symlinks(self, tmp_path: Path):
        hub = tmp_path / "hub"
        hub.mkdir()
        agent_dir = tmp_path / "agent_skills"
        agent_dir.mkdir()
        skill_dir = tmp_path / "src" / "cool-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("name: cool-skill")
        with mock.patch.object(skill_dirs_mod, "_SHARED_HUB", hub), \
             mock.patch.object(skill_dirs_mod, "_writable_agent_dirs", return_value=[agent_dir]):
            count = broadcast_evolved_skill(skill_dir, "cool-skill")
        assert (hub / "cool-skill" / "SKILL.md").exists()
        assert (agent_dir / "cool-skill").is_symlink()
        assert count == 1
