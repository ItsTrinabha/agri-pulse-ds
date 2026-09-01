"""Run each statement in queries.sql against agri_pulse.db and print results.
Used to verify the query file during development; also a runnable demo of
"you can solve common analytical questions in SQL" (Phase 4 exit criteria).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def split_statements(sql_text: str) -> list[tuple[str, str]]:
    """Split queries.sql into (comment_header, statement) pairs on the
    '-- Q<n>.' markers."""
    blocks = sql_text.split("-- Q")[1:]
    statements = []
    for block in blocks:
        lines = block.strip().splitlines()
        header = lines[0]
        body = "\n".join(lines[1:]).strip()
        statements.append((f"Q{header}", body))
    return statements


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    db_path = project_root / "data" / "processed" / "agri_pulse.db"
    queries_path = project_root / "database" / "queries.sql"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    for header, body in split_statements(queries_path.read_text(encoding="utf-8")):
        print(f"\n=== {header} ===")
        rows = conn.execute(body).fetchall()
        print(f"({len(rows)} rows)")
        for row in rows[:5]:
            print(dict(row))

    conn.close()
