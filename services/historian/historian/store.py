"""SQLite storage for the historian: numeric samples and discrete events."""

import sqlite3
from collections.abc import Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (ts REAL NOT NULL, tag TEXT NOT NULL, value REAL NOT NULL);
CREATE INDEX IF NOT EXISTS samples_tag_ts ON samples (tag, ts);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, message TEXT NOT NULL
);
"""


class Store:
    # shortcut: rows are kept forever (~1.5M/day); add a retention job if the lab runs for weeks.
    def __init__(self, path: str = ":memory:"):
        # All access happens from the single asyncio event loop, so one shared connection is safe.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    def record(self, ts: float, values: dict[str, float], events: Sequence[tuple[str, str, str]] = ()) -> None:
        """Store one poll: numeric tag values plus any (kind, name, message) events."""
        with self.db:
            self.db.executemany("INSERT INTO samples VALUES (?, ?, ?)", [(ts, k, v) for k, v in values.items()])
            self.db.executemany(
                "INSERT INTO events (ts, kind, name, message) VALUES (?, ?, ?, ?)", [(ts, *e) for e in events]
            )

    def series(self, tag: str, start: float, end: float, limit: int = 5000) -> list[list[float]]:
        """[[ts, value], ...] oldest first. If there are more than `limit`, the newest are kept."""
        rows = self.db.execute(
            "SELECT ts, value FROM samples WHERE tag = ? AND ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT ?",
            (tag, start, end, limit),
        ).fetchall()
        return [list(r) for r in reversed(rows)]

    def events(self, limit: int = 100, kind: str | None = None) -> list[dict]:
        """Newest first."""
        rows = self.db.execute(
            "SELECT id, ts, kind, name, message FROM events WHERE (? IS NULL OR kind = ?) ORDER BY id DESC LIMIT ?",
            (kind, kind, limit),
        ).fetchall()
        return [dict(zip(("id", "ts", "kind", "name", "message"), r, strict=True)) for r in rows]

    def clear(self) -> None:
        with self.db:
            self.db.execute("DELETE FROM samples")
            self.db.execute("DELETE FROM events")
