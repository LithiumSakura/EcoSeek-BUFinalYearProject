"""
EcoSeek — Unit Tests
Run with: pytest tests/ -v
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scoring import calculate_points, get_level


# ── calculate_points tests ───────────────────────────────────────

class TestCalculatePoints:

    def test_new_species_gives_50_xp(self):
        """A brand new species should award 50 XP."""
        assert calculate_points("Robin", is_new=True) == 50

    def test_repeat_species_gives_5_xp(self):
        """A repeat sighting should only award 5 XP."""
        assert calculate_points("Robin", is_new=False) == 5

    def test_new_species_with_streak_bonus(self):
        """New species + 7-day streak should award 50 + 10 = 60 XP."""
        assert calculate_points("Butterfly", is_new=True, streak_days=7) == 60

    def test_repeat_with_streak_bonus(self):
        """Repeat + 7-day streak should award 5 + 10 = 15 XP."""
        assert calculate_points("Butterfly", is_new=False, streak_days=7) == 15

    def test_streak_below_threshold_no_bonus(self):
        """A streak of 6 days should NOT give the streak bonus."""
        assert calculate_points("Daisy", is_new=True, streak_days=6) == 50

    def test_streak_exactly_at_threshold(self):
        """A streak of exactly 7 days SHOULD give the streak bonus."""
        assert calculate_points("Daisy", is_new=True, streak_days=7) == 60

    def test_long_streak_still_just_one_bonus(self):
        """A 30-day streak should still only give one 10 XP bonus."""
        assert calculate_points("Fox", is_new=True, streak_days=30) == 60

    def test_zero_streak_no_bonus(self):
        """Zero streak days should give no bonus."""
        assert calculate_points("Oak Tree", is_new=False, streak_days=0) == 5

    def test_species_name_does_not_affect_points(self):
        """Different species names should not change the XP calculation."""
        assert calculate_points("Rare Dragon", is_new=True) == \
               calculate_points("Common Weed",  is_new=True)

    def test_points_are_integers(self):
        """Points returned must always be integers."""
        pts = calculate_points("Bee", is_new=True)
        assert isinstance(pts, int)


# ── get_level tests ──────────────────────────────────────────────

class TestGetLevel:

    def test_zero_xp_is_seedling(self):
        result = get_level(0)
        assert result["level_name"] == "Seedling"
        assert result["level_num"]  == 0

    def test_100_xp_is_sprout(self):
        result = get_level(100)
        assert result["level_name"] == "Sprout"

    def test_progress_pct_is_between_0_and_100(self):
        for xp in [0, 50, 150, 500, 1000, 2500]:
            result = get_level(xp)
            assert 0 <= result["progress_pct"] <= 100

    def test_high_xp_reaches_master(self):
        result = get_level(2500)
        assert result["level_name"] == "Master Naturalist"

    def test_result_contains_required_keys(self):
        result = get_level(300)
        for key in ["level_num", "level_name", "xp_into_level", "xp_needed", "progress_pct"]:
            assert key in result

    def test_xp_into_level_is_non_negative(self):
        result = get_level(350)
        assert result["xp_into_level"] >= 0
