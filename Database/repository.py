import json
import sqlite3
from pathlib import Path

from CV.models import CV


class Repository:
    def __init__(self, database_path: str | Path = "job_finder.db") -> None:
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cvs (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    data TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT NOT NULL,
                    url TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source TEXT NOT NULL,
                    matched_terms TEXT NOT NULL DEFAULT '[]',
                    details TEXT NOT NULL DEFAULT '{}',
                    saved INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "details" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN details TEXT NOT NULL DEFAULT '{}'")

    def save_cv(self, cv: CV) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO cvs (id, data) VALUES (1, ?)",
                (cv.model_dump_json(),),
            )

    def get_cv(self) -> CV | None:
        with self._connect() as connection:
            row = connection.execute("SELECT data FROM cvs WHERE id = 1").fetchone()
        return CV.model_validate_json(row["data"]) if row else None

    def save_jobs(self, jobs: list[dict]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO jobs
                (external_id, title, company, location, url, description, source, matched_terms, details)
                VALUES (:external_id, :title, :company, :location, :url, :description, :source, :matched_terms, :details)
                ON CONFLICT(external_id) DO UPDATE SET
                    title = excluded.title,
                    company = excluded.company,
                    location = excluded.location,
                    url = excluded.url,
                    description = excluded.description,
                    source = excluded.source,
                    matched_terms = excluded.matched_terms,
                    details = excluded.details
                """,
                [
                    {
                        **job,
                        "matched_terms": json.dumps(job.get("matched_terms", [])),
                        "details": json.dumps(job.get("details", {})),
                    }
                    for job in jobs
                ],
            )

    def replace_jobs(self, jobs: list[dict], sources: list[str]) -> None:
        """Replace the previous result set for the sources used by one search."""
        placeholders = ", ".join("?" for _ in sources)
        with self._connect() as connection:
            connection.execute(f"DELETE FROM jobs WHERE source IN ({placeholders})", sources)
        self.save_jobs(jobs)

    def list_jobs(self, limit: int = 50) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {**dict(row), "matched_terms": json.loads(row["matched_terms"]), "details": json.loads(row["details"])}
            for row in rows
        ]
