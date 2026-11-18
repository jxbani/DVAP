"""SQLite storage for maintenance tickets."""

import sqlite3
import time

# Editable ticket columns. Column names in SQL below only ever come from this tuple.
FIELDS = (
    "title",
    "asset",
    "priority",
    "status",
    "description",
    "technician_notes",
    "attachments",
    "created_by",
)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    {", ".join(f"{f} TEXT NOT NULL DEFAULT ''" for f in FIELDS)},
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


class TicketStore:
    def __init__(self, path: str = ":memory:"):
        # All access happens from the single asyncio event loop, so one shared connection is safe.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def create(self, **fields: str) -> dict:
        assert set(fields) <= set(FIELDS)
        now = time.time()
        columns = [*fields, "created_at", "updated_at"]
        with self.db:
            cur = self.db.execute(
                f"INSERT INTO tickets ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                [*fields.values(), now, now],
            )
        ticket = self.get(cur.lastrowid) if cur.lastrowid else None
        assert ticket is not None, "a ticket just inserted must exist"
        return ticket

    def get(self, ticket_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return dict(row) if row else None

    def list(self, status: str | None = None, asset: str | None = None) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM tickets WHERE (?1 IS NULL OR status = ?1) AND (?2 IS NULL OR asset = ?2) ORDER BY id",
            (status, asset),
        ).fetchall()
        return [dict(r) for r in rows]

    def update(self, ticket_id: int, **fields: str) -> dict | None:
        assert set(fields) <= set(FIELDS)
        assignments = ", ".join(f"{f} = ?" for f in [*fields, "updated_at"])
        with self.db:
            self.db.execute(
                f"UPDATE tickets SET {assignments} WHERE id = ?", [*fields.values(), time.time(), ticket_id]
            )
        return self.get(ticket_id)

    def delete(self, ticket_id: int) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,)).rowcount > 0

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]

    def clear(self) -> None:
        """Remove all tickets and reset the id counter, so a re-seed is identical each time."""
        with self.db:
            self.db.execute("DELETE FROM tickets")
            self.db.execute("DELETE FROM sqlite_sequence WHERE name = 'tickets'")
