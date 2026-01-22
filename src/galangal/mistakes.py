"""
Mistake tracking with vector similarity search.

Tracks common AI mistakes in a repo to prevent them from recurring.
Uses sqlite-vss for semantic similarity matching.
"""

from __future__ import annotations

import json
import sqlite3
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from galangal.config.loader import get_project_root

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


# Embedding dimension for all-MiniLM-L6-v2 model
EMBEDDING_DIM = 384

# Similarity threshold for deduplication (lower = more similar)
DEDUP_THRESHOLD = 0.3

# Maximum mistakes to include in prompt warnings
MAX_PROMPT_WARNINGS = 5


@dataclass
class Mistake:
    """A recorded mistake from a previous task."""

    id: int
    description: str
    feedback: str
    stage: str
    file_patterns: list[str]
    occurrence_count: int
    last_task: str
    last_timestamp: int
    example_tasks: list[str]

    @property
    def age_days(self) -> float:
        """Days since last occurrence."""
        return (time.time() - self.last_timestamp) / 86400


class MistakeTracker:
    """
    Track and retrieve common mistakes using vector similarity.

    Mistakes are stored in SQLite with vector embeddings for semantic search.
    Similar mistakes are deduplicated and merged to prevent unbounded growth.
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_project_root() / ".galangal" / "mistakes.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._model: SentenceTransformer | None = None
        self._vss_available: bool | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy connection initialization."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._init_tables()
        return self._conn

    @property
    def vss_available(self) -> bool:
        """Check if sqlite-vss extension is available."""
        if self._vss_available is None:
            try:
                self.conn.enable_load_extension(True)
                # Try to load vss extension
                # Location varies by installation method
                try:
                    self.conn.load_extension("vss0")
                except sqlite3.OperationalError:
                    try:
                        self.conn.load_extension("vector0")
                        self.conn.load_extension("vss0")
                    except sqlite3.OperationalError:
                        self._vss_available = False
                        return False
                self._vss_available = True
            except Exception:
                self._vss_available = False
        return self._vss_available

    @property
    def model(self) -> SentenceTransformer:
        """Lazy model initialization."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                # Small, fast model - runs locally, no API needed
                self._model = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError as e:
                raise ImportError(
                    "sentence-transformers required for mistake tracking. "
                    "Install with: pip install sentence-transformers"
                ) from e
        return self._model

    def _init_tables(self) -> None:
        """Initialize database tables."""
        # Main mistakes table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS mistakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                feedback TEXT NOT NULL,
                stage TEXT NOT NULL,
                file_patterns TEXT NOT NULL,  -- JSON array
                occurrence_count INTEGER DEFAULT 1,
                last_task TEXT NOT NULL,
                last_timestamp INTEGER NOT NULL,
                example_tasks TEXT NOT NULL,  -- JSON array
                embedding BLOB  -- Vector embedding
            )
        """)

        # Index for stage-based queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mistakes_stage
            ON mistakes(stage)
        """)

        # Create VSS virtual table if extension available
        if self.vss_available:
            try:
                self.conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS mistakes_vss USING vss0(
                        embedding({EMBEDDING_DIM})
                    )
                """)
            except sqlite3.OperationalError:
                # VSS table might already exist with different schema
                pass

        self.conn.commit()

    def _embed(self, text: str) -> list[float]:
        """Generate embedding for text."""
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def _serialize_embedding(self, embedding: list[float]) -> bytes:
        """Serialize embedding to bytes for SQLite storage."""
        return struct.pack(f"{len(embedding)}f", *embedding)

    def _deserialize_embedding(self, blob: bytes) -> list[float]:
        """Deserialize embedding from bytes."""
        n = len(blob) // 4  # 4 bytes per float
        return list(struct.unpack(f"{n}f", blob))

    def _cosine_distance(self, a: list[float], b: list[float]) -> float:
        """Calculate cosine distance between two normalized vectors."""
        # For normalized vectors, cosine distance = 1 - dot product
        dot = sum(x * y for x, y in zip(a, b))
        return 1 - dot

    def log(
        self,
        description: str,
        feedback: str,
        stage: str,
        task: str,
        files: list[str] | None = None,
    ) -> int:
        """
        Log a mistake, deduplicating with existing similar mistakes.

        Args:
            description: What went wrong (e.g., "Forgot null check on user object")
            feedback: How to fix/prevent it (e.g., "Always check if user exists")
            stage: Stage where mistake occurred (e.g., "DEV", "TEST")
            task: Task name where mistake occurred
            files: List of file patterns involved

        Returns:
            ID of the mistake (new or existing merged)
        """
        file_patterns = files or []
        embedding = self._embed(f"{description} {feedback}")
        embedding_blob = self._serialize_embedding(embedding)
        now = int(time.time())

        # Find similar existing mistake
        similar = self._find_similar(embedding, stage, threshold=DEDUP_THRESHOLD)

        if similar:
            # Merge with existing mistake
            mistake = similar[0]
            example_tasks = json.loads(
                self.conn.execute(
                    "SELECT example_tasks FROM mistakes WHERE id = ?", [mistake.id]
                ).fetchone()[0]
            )
            if task not in example_tasks:
                example_tasks.append(task)
                # Keep only last 5 examples
                example_tasks = example_tasks[-5:]

            # Merge file patterns
            existing_patterns = set(mistake.file_patterns)
            existing_patterns.update(file_patterns)

            # Update existing mistake
            self.conn.execute(
                """
                UPDATE mistakes SET
                    occurrence_count = occurrence_count + 1,
                    last_task = ?,
                    last_timestamp = ?,
                    example_tasks = ?,
                    file_patterns = ?
                WHERE id = ?
            """,
                [
                    task,
                    now,
                    json.dumps(example_tasks),
                    json.dumps(list(existing_patterns)),
                    mistake.id,
                ],
            )
            self.conn.commit()
            return mistake.id

        # Insert new mistake
        cursor = self.conn.execute(
            """
            INSERT INTO mistakes
            (description, feedback, stage, file_patterns, last_task, last_timestamp,
             example_tasks, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                description,
                feedback,
                stage,
                json.dumps(file_patterns),
                task,
                now,
                json.dumps([task]),
                embedding_blob,
            ],
        )
        mistake_id = cursor.lastrowid

        # Add to VSS index if available
        if self.vss_available and mistake_id:
            self.conn.execute(
                "INSERT INTO mistakes_vss (rowid, embedding) VALUES (?, ?)",
                [mistake_id, embedding_blob],
            )

        self.conn.commit()
        return mistake_id or 0

    def _find_similar(
        self,
        embedding: list[float],
        stage: str | None = None,
        threshold: float = 0.5,
        limit: int = 5,
    ) -> list[Mistake]:
        """Find similar mistakes using vector search."""
        embedding_blob = self._serialize_embedding(embedding)

        if self.vss_available:
            # Use VSS for efficient similarity search
            query = """
                SELECT m.*, v.distance
                FROM mistakes m
                JOIN (
                    SELECT rowid, distance
                    FROM mistakes_vss
                    WHERE vss_search(embedding, ?)
                    LIMIT ?
                ) v ON m.id = v.rowid
                WHERE v.distance < ?
            """
            params: list = [embedding_blob, limit * 2, threshold]

            if stage:
                query = query.replace("WHERE v.distance", "WHERE m.stage = ? AND v.distance")
                params.insert(0, stage)
                params[2] = limit * 2  # Adjust limit position

            rows = self.conn.execute(query, params).fetchall()
        else:
            # Fallback: load all and compute distances in Python
            query = "SELECT * FROM mistakes"
            params = []
            if stage:
                query += " WHERE stage = ?"
                params = [stage]

            rows = []
            for row in self.conn.execute(query, params).fetchall():
                if row["embedding"]:
                    row_embedding = self._deserialize_embedding(row["embedding"])
                    distance = self._cosine_distance(embedding, row_embedding)
                    if distance < threshold:
                        # Convert to dict and add distance
                        row_dict = dict(row)
                        row_dict["distance"] = distance
                        rows.append(row_dict)

            # Sort by distance
            rows.sort(key=lambda x: x["distance"])
            rows = rows[:limit]

        return [self._row_to_mistake(row) for row in rows]

    def _row_to_mistake(self, row: sqlite3.Row | dict) -> Mistake:
        """Convert database row to Mistake object."""
        if isinstance(row, sqlite3.Row):
            row = dict(row)
        return Mistake(
            id=row["id"],
            description=row["description"],
            feedback=row["feedback"],
            stage=row["stage"],
            file_patterns=json.loads(row["file_patterns"]),
            occurrence_count=row["occurrence_count"],
            last_task=row["last_task"],
            last_timestamp=row["last_timestamp"],
            example_tasks=json.loads(row["example_tasks"]),
        )

    def get_warnings_for_stage(
        self,
        stage: str,
        files: list[str] | None = None,
        task_description: str | None = None,
    ) -> list[Mistake]:
        """
        Get relevant mistakes to warn about for a stage.

        Args:
            stage: Current stage (e.g., "DEV", "TEST")
            files: Files that will be changed (for pattern matching)
            task_description: Current task description (for semantic matching)

        Returns:
            List of relevant mistakes, ranked by relevance
        """
        mistakes: list[Mistake] = []
        seen_ids: set[int] = set()

        # 1. Get mistakes for this stage by frequency
        stage_mistakes = self.conn.execute(
            """
            SELECT * FROM mistakes
            WHERE stage = ?
            ORDER BY occurrence_count DESC, last_timestamp DESC
            LIMIT ?
        """,
            [stage, MAX_PROMPT_WARNINGS * 2],
        ).fetchall()

        for row in stage_mistakes:
            mistake = self._row_to_mistake(row)
            if mistake.id not in seen_ids:
                mistakes.append(mistake)
                seen_ids.add(mistake.id)

        # 2. If task description provided, find semantically similar
        if task_description:
            embedding = self._embed(task_description)
            similar = self._find_similar(embedding, stage=None, threshold=0.5, limit=5)
            for mistake in similar:
                if mistake.id not in seen_ids:
                    mistakes.append(mistake)
                    seen_ids.add(mistake.id)

        # 3. If files provided, match by file patterns
        if files:
            for mistake in list(mistakes):
                # Boost mistakes that match file patterns
                if self._matches_files(mistake.file_patterns, files):
                    # Move to front
                    mistakes.remove(mistake)
                    mistakes.insert(0, mistake)

            # Also search for file-pattern matches not yet included
            all_mistakes = self.conn.execute("SELECT * FROM mistakes").fetchall()
            for row in all_mistakes:
                mistake = self._row_to_mistake(row)
                if mistake.id not in seen_ids:
                    if self._matches_files(mistake.file_patterns, files):
                        mistakes.append(mistake)
                        seen_ids.add(mistake.id)

        # Sort by occurrence count (most common first), then recency
        mistakes.sort(key=lambda m: (-m.occurrence_count, -m.last_timestamp))

        return mistakes[:MAX_PROMPT_WARNINGS]

    def _matches_files(self, patterns: list[str], files: list[str]) -> bool:
        """Check if any file matches any pattern."""
        from fnmatch import fnmatch

        for pattern in patterns:
            for file in files:
                if fnmatch(file, pattern) or fnmatch(file, f"*/{pattern}"):
                    return True
        return False

    def format_warnings_for_prompt(
        self,
        stage: str,
        files: list[str] | None = None,
        task_description: str | None = None,
    ) -> str:
        """
        Format mistake warnings for inclusion in AI prompt.

        Returns empty string if no relevant mistakes.
        """
        mistakes = self.get_warnings_for_stage(stage, files, task_description)

        if not mistakes:
            return ""

        lines = [
            "# Common Mistakes in This Repo - AVOID THESE",
            "",
            "The following mistakes have occurred before in this codebase. "
            "Learn from them and avoid repeating:",
            "",
        ]

        for i, mistake in enumerate(mistakes, 1):
            lines.append(f"## {i}. {mistake.description}")
            lines.append(f"**Occurrences:** {mistake.occurrence_count} times")
            if mistake.file_patterns:
                lines.append(f"**Files:** {', '.join(mistake.file_patterns)}")
            lines.append(f"**Prevention:** {mistake.feedback}")
            lines.append("")

        return "\n".join(lines)

    def get_all_mistakes(self, limit: int = 50) -> list[Mistake]:
        """Get all mistakes, ordered by occurrence count."""
        rows = self.conn.execute(
            """
            SELECT * FROM mistakes
            ORDER BY occurrence_count DESC, last_timestamp DESC
            LIMIT ?
        """,
            [limit],
        ).fetchall()
        return [self._row_to_mistake(row) for row in rows]

    def get_stats(self) -> dict:
        """Get statistics about tracked mistakes."""
        total = self.conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0]
        by_stage = dict(
            self.conn.execute(
                """
            SELECT stage, COUNT(*) as count
            FROM mistakes
            GROUP BY stage
            ORDER BY count DESC
        """
            ).fetchall()
        )
        total_occurrences = (
            self.conn.execute("SELECT SUM(occurrence_count) FROM mistakes").fetchone()[0] or 0
        )

        return {
            "total_unique": total,
            "total_occurrences": total_occurrences,
            "by_stage": by_stage,
            "vss_enabled": self.vss_available,
        }

    def delete(self, mistake_id: int) -> bool:
        """Delete a mistake by ID."""
        self.conn.execute("DELETE FROM mistakes WHERE id = ?", [mistake_id])
        if self.vss_available:
            self.conn.execute("DELETE FROM mistakes_vss WHERE rowid = ?", [mistake_id])
        self.conn.commit()
        return True

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
