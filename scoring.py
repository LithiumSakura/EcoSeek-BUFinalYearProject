"""
EcoSeek — Scoring System
Awards XP points per sighting.
  - New species (first time ever spotted): 50 XP
  - Repeat sighting (seen before):          5 XP
  - Streak bonus (7-day streak):           +10 XP on top of base
"""

NEW_SPECIES_POINTS  = 50
REPEAT_POINTS       = 5
STREAK_BONUS        = 10
STREAK_THRESHOLD    = 7   # days for bonus to apply


def calculate_points(species: str, is_new: bool, streak_days: int = 0) -> int:
    """
    Return the XP to award for a sighting.

    Args:
        species:     Name of the identified species (unused in logic, kept for logging).
        is_new:      True if this is the user's first sighting of this species.
        streak_days: Current daily streak length for the user.

    Returns:
        Total integer XP to add to the user's score.
    """
    base = NEW_SPECIES_POINTS if is_new else REPEAT_POINTS
    bonus = STREAK_BONUS if streak_days >= STREAK_THRESHOLD else 0
    return base + bonus


def get_level(total_xp: int) -> dict:
    """
    Convert total XP into a level name and progress to next level.

    Returns a dict with:
        level_num   (int)
        level_name  (str)
        xp_into_level (int)
        xp_needed   (int)  — XP needed to reach NEXT level
        progress_pct (float) 0-100
    """
    thresholds = [
        (0,    "Seedling"),
        (100,  "Sprout"),
        (300,  "Explorer"),
        (600,  "Nature Scout"),
        (1000, "Wildlife Ranger"),
        (1500, "Eco Guardian"),
        (2500, "Master Naturalist"),
    ]

    level_num = 0
    level_name = thresholds[0][1]

    for i, (xp_req, name) in enumerate(thresholds):
        if total_xp >= xp_req:
            level_num = i
            level_name = name
        else:
            break

    # Progress within current level
    current_floor = thresholds[level_num][0]
    next_floor = thresholds[level_num + 1][0] if level_num + 1 < len(thresholds) else current_floor + 1000
    xp_into_level = total_xp - current_floor
    xp_needed = next_floor - current_floor
    progress_pct = round((xp_into_level / xp_needed) * 100, 1)

    return {
        "level_num":     level_num,
        "level_name":    level_name,
        "xp_into_level": xp_into_level,
        "xp_needed":     xp_needed,
        "progress_pct":  min(progress_pct, 100.0),
    }
