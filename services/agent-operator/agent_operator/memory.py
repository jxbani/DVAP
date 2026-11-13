"""The operator agent's long-term memory: "operator notes" persisted in SQLite.

Retrieval is keyword search ranked with BM25, using SQLite's built-in FTS5 index, so
there is no vector database to run.
"""

import re
import sqlite3
import time


class MemoryStore:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notes USING fts5(key, content, source UNINDEXED, created_at UNINDEXED)"
        )

    def write(self, key: str, content: str, source: str) -> dict:
        """Store a note, replacing any existing note with the same key.

        DVAP-VULN: C06 - no provenance checks. `source` is whatever the caller claims, nothing
        verifies where `content` really came from, and existing notes can be overwritten. Text
        the agent "learned" from an attacker-written ticket is stored, and later retrieved,
        exactly like a note from a trusted operator.
        """
        with self.db:
            self.db.execute("DELETE FROM notes WHERE key = ?", (key,))
            self.db.execute("INSERT INTO notes VALUES (?, ?, ?, ?)", (key, content, source, time.time()))
        return self.read(key)

    def read(self, key: str) -> dict | None:
        row = self.db.execute("SELECT * FROM notes WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None

    def all(self) -> list[dict]:
        """Every note, oldest first."""
        return [dict(r) for r in self.db.execute("SELECT * FROM notes ORDER BY created_at, rowid")]

    def delete(self, key: str) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM notes WHERE key = ?", (key,)).rowcount > 0

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """The notes that best match any word of `query`, best first, each with a `score`."""
        # Quote every word so the text is matched literally, never parsed as FTS5 query syntax.
        words = re.findall(r"\w+", query)
        if not words:
            return []
        rows = self.db.execute(
            # bm25() is "lower is better" (negative); flip it so a higher score means a better match.
            "SELECT *, -bm25(notes) AS score FROM notes WHERE notes MATCH ? ORDER BY bm25(notes) LIMIT ?",
            (" OR ".join(f'"{w}"' for w in words), limit),
        ).fetchall()
        return [dict(r) for r in rows]
