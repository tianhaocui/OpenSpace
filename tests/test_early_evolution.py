"""Tests for the consecutive-failure early evolution path in report_skill_usage."""

from __future__ import annotations

import json
from datetime import datetime
from unittest import mock

import pytest

from openspace.skill_engine.types import (
    ExecutionAnalysis,
    EvolutionSuggestion,
    EvolutionType,
    SkillJudgment,
)


def _make_analysis(
    skill_id: str,
    task_completed: bool,
    skill_applied: bool = True,
    note: str = "",
) -> ExecutionAnalysis:
    return ExecutionAnalysis(
        task_id=f"test-{id(skill_id)}",
        timestamp=datetime.now(),
        task_completed=task_completed,
        execution_note=note,
        skill_judgments=[
            SkillJudgment(
                skill_id=skill_id,
                skill_applied=skill_applied,
                note=note,
            ),
        ],
    )


class TestConsecutiveFailureDetection:
    """Test the consecutive failure logic extracted from _report_skill_usage_core."""

    @staticmethod
    def _should_early_evolve(
        skill_id: str,
        task_completed: bool,
        skill_applied: bool,
        total_selections: int,
        recent_analyses: list[ExecutionAnalysis],
    ) -> bool:
        """Mirror the consecutive-failure check from mcp_server.py."""
        if not (not task_completed and skill_applied and total_selections >= 3):
            return False
        if len(recent_analyses) < 3:
            return False
        return all(
            not a.task_completed
            and any(
                j.skill_applied
                for j in a.skill_judgments
                if j.skill_id == skill_id
            )
            for a in recent_analyses[-3:]
        )

    def test_three_consecutive_failures_triggers(self):
        sid = "test-skill-001"
        analyses = [
            _make_analysis(sid, task_completed=False, note="fail 1"),
            _make_analysis(sid, task_completed=False, note="fail 2"),
            _make_analysis(sid, task_completed=False, note="fail 3"),
        ]
        assert self._should_early_evolve(
            sid, task_completed=False, skill_applied=True,
            total_selections=3, recent_analyses=analyses,
        )

    def test_two_failures_does_not_trigger(self):
        sid = "test-skill-002"
        analyses = [
            _make_analysis(sid, task_completed=False),
            _make_analysis(sid, task_completed=False),
        ]
        assert not self._should_early_evolve(
            sid, task_completed=False, skill_applied=True,
            total_selections=2, recent_analyses=analyses,
        )

    def test_mixed_results_does_not_trigger(self):
        sid = "test-skill-003"
        analyses = [
            _make_analysis(sid, task_completed=False),
            _make_analysis(sid, task_completed=True),  # success breaks streak
            _make_analysis(sid, task_completed=False),
        ]
        assert not self._should_early_evolve(
            sid, task_completed=False, skill_applied=True,
            total_selections=3, recent_analyses=analyses,
        )

    def test_not_applied_does_not_trigger(self):
        sid = "test-skill-004"
        analyses = [
            _make_analysis(sid, task_completed=False, skill_applied=False),
            _make_analysis(sid, task_completed=False, skill_applied=False),
            _make_analysis(sid, task_completed=False, skill_applied=False),
        ]
        assert not self._should_early_evolve(
            sid, task_completed=False, skill_applied=True,
            total_selections=3, recent_analyses=analyses,
        )

    def test_success_report_does_not_trigger(self):
        sid = "test-skill-005"
        analyses = [
            _make_analysis(sid, task_completed=False),
            _make_analysis(sid, task_completed=False),
            _make_analysis(sid, task_completed=False),
        ]
        # Current report is a success
        assert not self._should_early_evolve(
            sid, task_completed=True, skill_applied=True,
            total_selections=3, recent_analyses=analyses,
        )

    def test_below_min_selections_does_not_trigger(self):
        sid = "test-skill-006"
        analyses = [
            _make_analysis(sid, task_completed=False),
            _make_analysis(sid, task_completed=False),
            _make_analysis(sid, task_completed=False),
        ]
        assert not self._should_early_evolve(
            sid, task_completed=False, skill_applied=True,
            total_selections=2, recent_analyses=analyses,
        )


class TestEvolutionSuggestionConstruction:
    """Verify the EvolutionSuggestion built for early evolution."""

    def test_suggestion_includes_notes(self):
        sid = "test-skill-007"
        analyses = [
            _make_analysis(sid, task_completed=False, note="API 404"),
            _make_analysis(sid, task_completed=False, note="timeout"),
            _make_analysis(sid, task_completed=False, note="wrong endpoint"),
        ]
        notes = [
            j.note for a in analyses[-3:]
            for j in a.skill_judgments
            if j.skill_id == sid and j.note
        ]
        suggestion = EvolutionSuggestion(
            evolution_type=EvolutionType.FIX,
            target_skill_ids=[sid],
            direction=f"Skill failed 3 consecutive times. Notes: {'; '.join(notes[-3:])}",
        )
        assert suggestion.evolution_type == EvolutionType.FIX
        assert sid in suggestion.target_skill_ids
        assert "API 404" in suggestion.direction
        assert "timeout" in suggestion.direction
        assert "wrong endpoint" in suggestion.direction


class TestConsecutiveNotesDetection:
    """Test the consecutive-notes logic for Score B/C (效果不好) scenarios."""

    @staticmethod
    def _should_early_evolve_notes(
        skill_id: str,
        skill_applied: bool,
        note: str,
        total_selections: int,
        recent_analyses: list[ExecutionAnalysis],
    ) -> bool:
        """Mirror the consecutive-notes check from mcp_server.py."""
        if not (skill_applied and note and total_selections >= 3):
            return False
        if len(recent_analyses) < 3:
            return False
        return all(
            any(
                j.note and j.skill_applied
                for j in a.skill_judgments
                if j.skill_id == skill_id
            )
            for a in recent_analyses[-3:]
        )

    def test_three_consecutive_notes_triggers(self):
        sid = "test-skill-note-001"
        analyses = [
            _make_analysis(sid, task_completed=True, note="API endpoint outdated"),
            _make_analysis(sid, task_completed=True, note="missing retry logic"),
            _make_analysis(sid, task_completed=True, note="wrong auth header format"),
        ]
        assert self._should_early_evolve_notes(
            sid, skill_applied=True, note="wrong auth header format",
            total_selections=3, recent_analyses=analyses,
        )

    def test_mixed_notes_and_no_notes_does_not_trigger(self):
        sid = "test-skill-note-002"
        analyses = [
            _make_analysis(sid, task_completed=True, note="issue 1"),
            _make_analysis(sid, task_completed=True, note=""),  # Score A, no note
            _make_analysis(sid, task_completed=True, note="issue 2"),
        ]
        assert not self._should_early_evolve_notes(
            sid, skill_applied=True, note="issue 2",
            total_selections=3, recent_analyses=analyses,
        )

    def test_not_applied_does_not_trigger(self):
        sid = "test-skill-note-003"
        analyses = [
            _make_analysis(sid, task_completed=True, skill_applied=False, note="n1"),
            _make_analysis(sid, task_completed=True, skill_applied=False, note="n2"),
            _make_analysis(sid, task_completed=True, skill_applied=False, note="n3"),
        ]
        assert not self._should_early_evolve_notes(
            sid, skill_applied=True, note="n3",
            total_selections=3, recent_analyses=analyses,
        )

    def test_no_note_in_current_report_does_not_trigger(self):
        sid = "test-skill-note-004"
        analyses = [
            _make_analysis(sid, task_completed=True, note="issue 1"),
            _make_analysis(sid, task_completed=True, note="issue 2"),
            _make_analysis(sid, task_completed=True, note="issue 3"),
        ]
        assert not self._should_early_evolve_notes(
            sid, skill_applied=True, note="",  # current report has no note
            total_selections=3, recent_analyses=analyses,
        )
