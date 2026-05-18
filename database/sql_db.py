import sqlite3
import os
from contextlib import contextmanager


DB_PATH = os.environ.get(
    "SQL_DB_PATH",
    "/tmp/ecoseek.db" if os.environ.get("GAE_ENV") else "ecoseek.db"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leaderboard (
    user_id       TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL DEFAULT 'Explorer',
    total_points  INTEGER NOT NULL DEFAULT 0,
    species_count INTEGER NOT NULL DEFAULT 0,
    streak_days   INTEGER NOT NULL DEFAULT 0,
    last_seen     TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sighting_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    species     TEXT NOT NULL,
    category    TEXT,
    points      INTEGER,
    is_new      INTEGER DEFAULT 0,
    logged_at   TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES leaderboard(user_id)
);
"""


def init_db():
    with get_db_connection() as conn:
        conn.executescript(_SCHEMA)
        conn.commit()

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()

def upsert_user(user_id: str, display_name: str):
    # Adding user to leaderboard if they aren't already on there
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO leaderboard (user_id, display_name)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name = excluded.display_name
        """, (user_id, display_name))
        conn.commit()

def add_points(user_id: str, points: int, is_new_species: bool):
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE leaderboard
            SET total_points  = total_points + ?,
                species_count = species_count + ?,
                last_seen     = datetime('now')
            WHERE user_id = ?
        """, (points, 1 if is_new_species else 0, user_id))
        conn.commit()

def get_top_users(limit: int = 20) -> list:
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT user_id, display_name, total_points, species_count, streak_days
            FROM leaderboard
            ORDER BY total_points DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]

def get_user_rank(user_id: str) -> int:
    with get_db_connection() as conn:
        result = conn.execute("""
            SELECT COUNT(*) + 1 AS rank
            FROM leaderboard
            WHERE total_points > (
                SELECT COALESCE(total_points, 0) FROM leaderboard WHERE user_id = ?
            )
        """, (user_id,)).fetchone()
    return result["rank"] if result else 1

def log_sighting(user_id: str, species: str, category: str, points: int, is_new: bool):
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO sighting_log (user_id, species, category, points, is_new)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, species, category, points, 1 if is_new else 0))
        conn.commit()