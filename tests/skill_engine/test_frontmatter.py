"""Tests for skill_utils.py — frontmatter parsing (enhanced)."""

from __future__ import annotations
from openspace.skill_engine.skill_utils import parse_frontmatter


class TestParseFrontmatter:

    def test_simple_key_value(self):
        content = "---\nname: my-skill\ndescription: A test\n---\nBody."
        fm = parse_frontmatter(content)
        assert fm["name"] == "my-skill"
        assert fm["description"] == "A test"

    def test_inline_list_as_string(self):
        """On main, parse_frontmatter returns inline lists as raw strings."""
        content = "---\nname: test\ntags: [web, api, hermes]\n---\nBody."
        fm = parse_frontmatter(content)
        # Simple parser returns the raw string; _parse_tag_value handles conversion
        assert "tags" in fm

    def test_nested_key_as_string(self):
        """On main, nested YAML is returned as flat key:value strings."""
        content = "---\nname: test\nmetadata:\n  key: value\n---\nBody."
        fm = parse_frontmatter(content)
        assert fm["name"] == "test"

    def test_quoted_value(self):
        content = '---\nname: "my skill"\nversion: "2.0"\n---\nBody.'
        fm = parse_frontmatter(content)
        assert fm["name"] == "my skill"
        assert fm["version"] == "2.0"

    def test_no_frontmatter(self):
        assert parse_frontmatter("No frontmatter here.") == {}

    def test_empty_content(self):
        assert parse_frontmatter("") == {}
