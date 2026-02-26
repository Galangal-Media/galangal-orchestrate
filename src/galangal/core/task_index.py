"""SQLite task index and canonical artifact store.

Breaking migration note:
- Task artifacts are now canonical in SQLite (`.galangal/tasks.db`), not filesystem files.
- Legacy artifact files are imported into SQLite and deleted during migration.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from galangal.config.loader import get_done_dir, get_project_root, get_tasks_dir

if TYPE_CHECKING:
    from galangal.core.state import WorkflowState


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


MIRRORED_ARTIFACT_FILES = frozenset({"PLAN.md", "SUMMARY.md"})


@dataclass(frozen=True)
class TaskIndexStats:
    """Summary of task index contents."""

    db_path: Path
    total_tasks: int
    total_artifacts: int
    tasks_by_status: dict[str, int]


class TaskIndex:
    """SQLite-backed task index and artifact storage."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (get_project_root() / ".galangal" / "tasks.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self, *, bootstrap: bool = True) -> sqlite3.Connection:
        """Open and initialize a SQLite connection."""
        try:
            return self._open_and_init(bootstrap=bootstrap)
        except sqlite3.DatabaseError:
            if not self.db_path.exists():
                raise

            from rich.prompt import Confirm

            print(f"\n[!] Task index database is corrupted: {self.db_path}")
            if Confirm.ask(
                "Delete the corrupted database and rebuild from task files?",
                default=True,
            ):
                self.db_path.unlink(missing_ok=True)
                # Also remove WAL/SHM journal files if present.
                for suffix in ("-wal", "-shm"):
                    self.db_path.with_name(self.db_path.name + suffix).unlink(
                        missing_ok=True
                    )
                return self._open_and_init(bootstrap=bootstrap)
            raise

    def _open_and_init(self, *, bootstrap: bool = True) -> sqlite3.Connection:
        """Open DB file, set pragmas, init schema, and optionally bootstrap."""
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.DatabaseError:
            conn.close()
            raise

        self._init_schema(conn)
        if bootstrap:
            self._ensure_bootstrapped(conn)
        return conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        """Create tables/indexes and apply additive schema migrations."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS task_index_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_name TEXT PRIMARY KEY,
                task_description TEXT NOT NULL DEFAULT '',
                task_type TEXT NOT NULL DEFAULT 'feature',
                stage TEXT NOT NULL DEFAULT 'PM',
                attempt INTEGER NOT NULL DEFAULT 1,
                awaiting_approval INTEGER NOT NULL DEFAULT 0,
                clarification_required INTEGER NOT NULL DEFAULT 0,
                last_failure TEXT,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                location TEXT NOT NULL,
                github_issue INTEGER,
                github_repo TEXT
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                task_name TEXT NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                stage TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT,
                preview TEXT,
                is_present INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (task_name, name),
                FOREIGN KEY (task_name) REFERENCES tasks(task_name) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT NOT NULL,
                logged_at TEXT NOT NULL,
                line_type TEXT NOT NULL DEFAULT 'raw',
                line TEXT NOT NULL,
                FOREIGN KEY (task_name) REFERENCES tasks(task_name) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_stage ON tasks(stage);
            CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at);
            CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_name);
            CREATE INDEX IF NOT EXISTS idx_artifacts_present ON artifacts(is_present);
            CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_name, id);
            """
        )

        artifact_columns = {
            str(row["name"]) for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()
        }
        if "content" not in artifact_columns:
            conn.execute("ALTER TABLE artifacts ADD COLUMN content TEXT NOT NULL DEFAULT ''")

        conn.commit()

    def _get_meta(self, conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute(
            "SELECT value FROM task_index_meta WHERE key = ?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row else None

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            """
            INSERT INTO task_index_meta (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def _ensure_bootstrapped(self, conn: sqlite3.Connection) -> None:
        """Run one-time DB bootstrap and legacy artifact migration."""
        if self._get_meta(conn, "bootstrapped") == "1":
            return

        self._sync_task_rows_from_filesystem(conn)
        self._migrate_all_legacy_artifacts(conn, delete_files=True)
        self._set_meta(conn, "bootstrapped", "1")
        conn.commit()

    def _rel_path(self, path: Path) -> str:
        """Return project-relative path string when possible."""
        project_root = get_project_root().resolve()
        try:
            return str(path.resolve().relative_to(project_root))
        except ValueError:
            return str(path)

    def _iter_task_dirs(self) -> list[tuple[Path, str]]:
        """Return [(task_dir, status), ...] for active and done task directories."""
        rows: list[tuple[Path, str]] = []

        tasks_dir = get_tasks_dir()
        if tasks_dir.exists():
            for task_dir in sorted(tasks_dir.iterdir()):
                if not task_dir.is_dir() or task_dir.name.startswith("."):
                    continue
                if task_dir.name in {"done", ".archive"}:
                    continue
                rows.append((task_dir, "active"))

        done_dir = get_done_dir()
        if done_dir.exists():
            for task_dir in sorted(done_dir.iterdir()):
                if not task_dir.is_dir() or task_dir.name.startswith("."):
                    continue
                rows.append((task_dir, "done"))

        return rows

    def _is_indexable_artifact_name(self, name: str) -> bool:
        """Return whether a filename is an artifact we track."""
        if name.endswith(".md"):
            return True
        if "." not in name and name.upper() == name and any(c.isalpha() for c in name):
            return True
        return False

    def _is_mirrored_artifact(self, name: str) -> bool:
        """Return whether this artifact should also exist as a task file."""
        return name in MIRRORED_ARTIFACT_FILES

    def _resolve_mirror_path(self, task_name: str, name: str) -> Path:
        """Resolve preferred mirror path for an artifact."""
        done_dir = get_done_dir() / task_name
        if done_dir.exists():
            return done_dir / name
        return (get_tasks_dir() / task_name) / name

    def _write_mirror_artifact_file(self, *, task_name: str, name: str, content: str) -> bool:
        """Write mirrored artifact content to filesystem."""
        if not self._is_mirrored_artifact(name):
            return False
        path = self._resolve_mirror_path(task_name, name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return True
        except OSError:
            return False

    def _artifact_preview(self, content: str, max_chars: int = 600) -> str:
        """Generate a compact one-line preview of artifact content."""
        compact = " ".join(content.split())
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars].rstrip() + "..."

    def _upsert_task_record(
        self,
        conn: sqlite3.Connection,
        *,
        task_name: str,
        task_description: str,
        task_type: str,
        stage: str,
        attempt: int,
        awaiting_approval: bool,
        clarification_required: bool,
        last_failure: str | None,
        started_at: str | None,
        completed_at: str | None,
        updated_at: str,
        status: str,
        location: str,
        github_issue: int | None,
        github_repo: str | None,
    ) -> None:
        """Insert or update one task row."""
        conn.execute(
            """
            INSERT INTO tasks (
                task_name,
                task_description,
                task_type,
                stage,
                attempt,
                awaiting_approval,
                clarification_required,
                last_failure,
                started_at,
                completed_at,
                updated_at,
                status,
                location,
                github_issue,
                github_repo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_name) DO UPDATE SET
                task_description = excluded.task_description,
                task_type = excluded.task_type,
                stage = excluded.stage,
                attempt = excluded.attempt,
                awaiting_approval = excluded.awaiting_approval,
                clarification_required = excluded.clarification_required,
                last_failure = excluded.last_failure,
                started_at = excluded.started_at,
                completed_at = COALESCE(tasks.completed_at, excluded.completed_at),
                updated_at = excluded.updated_at,
                status = excluded.status,
                location = excluded.location,
                github_issue = excluded.github_issue,
                github_repo = excluded.github_repo
            """,
            (
                task_name,
                task_description,
                task_type,
                stage,
                attempt,
                1 if awaiting_approval else 0,
                1 if clarification_required else 0,
                last_failure,
                started_at,
                completed_at,
                updated_at,
                status,
                location,
                github_issue,
                github_repo,
            ),
        )

    def _extract_state_for_dir(self, task_dir: Path) -> dict[str, Any]:
        """Read state.json for a task directory."""
        state_path = task_dir / "state.json"
        if not state_path.exists():
            return {}

        try:
            return json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _upsert_task_from_dir(self, conn: sqlite3.Connection, task_dir: Path, status: str) -> None:
        """Upsert task row from a task directory and state.json."""
        state = self._extract_state_for_dir(task_dir)

        state_path = task_dir / "state.json"
        if state_path.exists():
            updated_at = datetime.fromtimestamp(state_path.stat().st_mtime, timezone.utc).isoformat()
        else:
            updated_at = _now_iso()

        stage = str(state.get("stage", "PM"))
        completed_at = state.get("completed_at")
        if not completed_at and stage == "COMPLETE":
            completed_at = updated_at

        self._upsert_task_record(
            conn,
            task_name=task_dir.name,
            task_description=str(state.get("task_description", "")),
            task_type=str(state.get("task_type", "feature")),
            stage=stage,
            attempt=int(state.get("attempt", 1) or 1),
            awaiting_approval=bool(state.get("awaiting_approval", False)),
            clarification_required=bool(state.get("clarification_required", False)),
            last_failure=state.get("last_failure"),
            started_at=state.get("started_at"),
            completed_at=completed_at,
            updated_at=updated_at,
            status=status,
            location=self._rel_path(task_dir),
            github_issue=state.get("github_issue"),
            github_repo=state.get("github_repo"),
        )

    def _sync_task_rows_from_filesystem(self, conn: sqlite3.Connection) -> dict[str, int]:
        """Rebuild active/done task rows from current task directories."""
        conn.execute("DELETE FROM tasks WHERE status IN ('active', 'done')")

        counts = {"active": 0, "done": 0, "archived": 0}

        for task_dir, status in self._iter_task_dirs():
            self._upsert_task_from_dir(conn, task_dir, status)
            counts[status] += 1

        archive_index = get_tasks_dir() / ".archive" / "index.json"
        if archive_index.exists():
            try:
                data = json.loads(archive_index.read_text())
                if isinstance(data, dict):
                    for task_name, meta in data.items():
                        if not isinstance(meta, dict):
                            continue
                        archived_at = str(meta.get("archived_at") or _now_iso())
                        self._upsert_task_record(
                            conn,
                            task_name=str(task_name),
                            task_description=str(meta.get("description", "")),
                            task_type=str(meta.get("task_type", "feature")),
                            stage=str(meta.get("stage", "COMPLETE")),
                            attempt=1,
                            awaiting_approval=False,
                            clarification_required=False,
                            last_failure=None,
                            started_at=meta.get("start_time"),
                            completed_at=archived_at,
                            updated_at=archived_at,
                            status="archived",
                            location=self._rel_path(get_tasks_dir() / ".archive" / str(task_name)),
                            github_issue=meta.get("github_issue"),
                            github_repo=None,
                        )
                        counts["archived"] += 1
            except (json.JSONDecodeError, OSError):
                pass

        conn.commit()
        return counts

    def _ensure_task_row(self, conn: sqlite3.Connection, task_name: str) -> None:
        """Ensure a task row exists for artifact operations."""
        row = conn.execute(
            "SELECT task_name FROM tasks WHERE task_name = ?",
            (task_name,),
        ).fetchone()
        if row:
            return

        active_dir = get_tasks_dir() / task_name
        done_dir = get_done_dir() / task_name

        if done_dir.exists():
            self._upsert_task_from_dir(conn, done_dir, "done")
            return

        if active_dir.exists():
            self._upsert_task_from_dir(conn, active_dir, "active")
            return

        now = _now_iso()
        self._upsert_task_record(
            conn,
            task_name=task_name,
            task_description="",
            task_type="feature",
            stage="PM",
            attempt=1,
            awaiting_approval=False,
            clarification_required=False,
            last_failure=None,
            started_at=now,
            completed_at=None,
            updated_at=now,
            status="active",
            location=self._rel_path(active_dir),
            github_issue=None,
            github_repo=None,
        )

    def _legacy_artifact_path(self, task_name: str, name: str) -> Path | None:
        """Return path for a legacy filesystem artifact if it exists."""
        for base in (get_tasks_dir() / task_name, get_done_dir() / task_name):
            path = base / name
            if path.exists() and path.is_file():
                return path
        return None

    def _delete_legacy_artifact_file(self, task_name: str, name: str) -> bool:
        """Delete legacy filesystem artifact file if present."""
        path = self._legacy_artifact_path(task_name, name)
        if not path:
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False

    def _upsert_artifact_conn(
        self,
        conn: sqlite3.Connection,
        *,
        task_name: str,
        name: str,
        content: str,
        stage: str | None = None,
    ) -> None:
        """Upsert one artifact row in an existing DB connection."""
        now = _now_iso()
        raw = content.encode("utf-8", errors="replace")

        conn.execute(
            """
            INSERT INTO artifacts (
                task_name,
                name,
                content,
                updated_at,
                stage,
                size_bytes,
                sha256,
                preview,
                is_present
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(task_name, name) DO UPDATE SET
                content = excluded.content,
                updated_at = excluded.updated_at,
                stage = COALESCE(excluded.stage, artifacts.stage),
                size_bytes = excluded.size_bytes,
                sha256 = excluded.sha256,
                preview = excluded.preview,
                is_present = 1
            """,
            (
                task_name,
                name,
                content,
                now,
                stage,
                len(raw),
                hashlib.sha256(raw).hexdigest(),
                self._artifact_preview(content),
            ),
        )
        conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE task_name = ?",
            (now, task_name),
        )

    def _migrate_legacy_artifact_conn(
        self,
        conn: sqlite3.Connection,
        *,
        task_name: str,
        name: str,
        delete_file: bool,
    ) -> bool:
        """Import one legacy artifact file to DB, optionally deleting the file."""
        path = self._legacy_artifact_path(task_name, name)
        if not path:
            return False

        try:
            content = path.read_text()
        except OSError:
            return False

        self._ensure_task_row(conn, task_name)
        self._upsert_artifact_conn(conn, task_name=task_name, name=name, content=content)

        if delete_file and not self._is_mirrored_artifact(name):
            try:
                path.unlink()
            except OSError:
                pass
        elif self._is_mirrored_artifact(name):
            self._write_mirror_artifact_file(task_name=task_name, name=name, content=content)

        return True

    def _migrate_all_legacy_artifacts(self, conn: sqlite3.Connection, *, delete_files: bool) -> dict[str, int]:
        """Import all legacy filesystem artifacts into SQLite."""
        migrated = 0
        deleted = 0

        for task_dir, status in self._iter_task_dirs():
            self._upsert_task_from_dir(conn, task_dir, status)
            for path in sorted(task_dir.iterdir()):
                if not path.is_file() or path.name == "state.json":
                    continue
                if not self._is_indexable_artifact_name(path.name):
                    continue

                try:
                    content = path.read_text()
                except OSError:
                    continue

                self._upsert_artifact_conn(
                    conn,
                    task_name=task_dir.name,
                    name=path.name,
                    content=content,
                )
                migrated += 1

                if delete_files:
                    if self._is_mirrored_artifact(path.name):
                        continue
                    try:
                        path.unlink()
                        deleted += 1
                    except OSError:
                        pass

            # Ensure mirrored artifacts exist on disk when present in DB.
            for mirror_name in MIRRORED_ARTIFACT_FILES:
                row = conn.execute(
                    """
                    SELECT content
                    FROM artifacts
                    WHERE task_name = ? AND name = ? AND is_present = 1
                    """,
                    (task_dir.name, mirror_name),
                ).fetchone()
                if row:
                    self._write_mirror_artifact_file(
                        task_name=task_dir.name,
                        name=mirror_name,
                        content=str(row["content"]),
                    )

        conn.commit()
        return {"migrated": migrated, "deleted": deleted}

    def rebuild(self) -> dict[str, int]:
        """Rebuild task rows and migrate any legacy artifact files to SQLite."""
        with self._connect(bootstrap=False) as conn:
            counts = self._sync_task_rows_from_filesystem(conn)
            migration = self._migrate_all_legacy_artifacts(conn, delete_files=True)
            self._set_meta(conn, "bootstrapped", "1")
            conn.commit()
            return {
                "active": counts.get("active", 0),
                "done": counts.get("done", 0),
                "archived": counts.get("archived", 0),
                "migrated": migration.get("migrated", 0),
                "deleted": migration.get("deleted", 0),
            }

    def migrate_artifacts(self, *, delete_files: bool = True) -> dict[str, int]:
        """Manually migrate legacy filesystem artifacts into SQLite."""
        with self._connect() as conn:
            return self._migrate_all_legacy_artifacts(conn, delete_files=delete_files)

    def ingest_task_artifacts(self, *, task_name: str) -> int:
        """Import filesystem artifacts for a single task into DB and delete originals.

        Called after each stage completes to ensure files written directly
        by editable backends (e.g. Claude ``Write`` tool) are captured in
        canonical DB storage.

        Returns:
            Number of artifacts ingested.
        """
        task_dir = get_tasks_dir() / task_name
        if not task_dir.is_dir():
            return 0

        ingested = 0
        with self._connect() as conn:
            self._ensure_task_row(conn, task_name)
            for path in sorted(task_dir.iterdir()):
                if not path.is_file() or path.name == "state.json":
                    continue
                if not self._is_indexable_artifact_name(path.name):
                    continue

                try:
                    content = path.read_text()
                except OSError:
                    continue

                self._upsert_artifact_conn(
                    conn,
                    task_name=task_name,
                    name=path.name,
                    content=content,
                )
                ingested += 1

                if not self._is_mirrored_artifact(path.name):
                    try:
                        path.unlink()
                    except OSError:
                        pass

            conn.commit()
        return ingested

    def compact_done_markdown(
        self,
        *,
        keep_markdown: tuple[str, ...] = ("PLAN.md", "SUMMARY.md"),
    ) -> dict[str, int]:
        """Strip done task folders to only selected markdown files.

        Behavior:
        - Imports any legacy markdown artifacts into SQLite first.
        - Deletes all markdown files in done task folders except those in ``keep_markdown``.
        - Rehydrates kept markdown files from DB content when missing.
        """
        keep_set = {name for name in keep_markdown if name.endswith(".md")}
        tasks_scanned = 0
        kept = 0
        deleted = 0
        restored = 0

        with self._connect(bootstrap=False) as conn:
            migration = self._migrate_all_legacy_artifacts(conn, delete_files=False)

            done_dir = get_done_dir()
            if done_dir.exists():
                for task_dir in sorted(done_dir.iterdir()):
                    if not task_dir.is_dir() or task_dir.name.startswith("."):
                        continue

                    tasks_scanned += 1
                    self._upsert_task_from_dir(conn, task_dir, "done")

                    for path in sorted(task_dir.iterdir()):
                        if not path.is_file() or not path.name.endswith(".md"):
                            continue
                        if path.name in keep_set:
                            kept += 1
                            continue
                        try:
                            path.unlink()
                            deleted += 1
                        except OSError:
                            pass

                    for name in sorted(keep_set):
                        keep_path = task_dir / name
                        if keep_path.exists():
                            continue
                        row = conn.execute(
                            """
                            SELECT content
                            FROM artifacts
                            WHERE task_name = ? AND name = ? AND is_present = 1
                            """,
                            (task_dir.name, name),
                        ).fetchone()
                        if not row:
                            continue
                        try:
                            keep_path.write_text(str(row["content"]))
                            restored += 1
                        except OSError:
                            pass

            self._set_meta(conn, "bootstrapped", "1")
            conn.commit()

        return {
            "tasks": tasks_scanned,
            "kept": kept,
            "deleted": deleted,
            "restored": restored,
            "migrated": migration.get("migrated", 0),
        }

    def upsert_state(self, state: WorkflowState) -> None:
        """Index latest workflow state for a task."""
        task_name = state.task_name
        active_path = get_tasks_dir() / task_name
        done_path = get_done_dir() / task_name

        status = "done" if done_path.exists() else "active"
        location = self._rel_path(done_path if done_path.exists() else active_path)

        now = _now_iso()
        completed_at = now if state.stage.value == "COMPLETE" else None

        with self._connect() as conn:
            self._upsert_task_record(
                conn,
                task_name=task_name,
                task_description=state.task_description,
                task_type=state.task_type.value,
                stage=state.stage.value,
                attempt=state.attempt,
                awaiting_approval=state.awaiting_approval,
                clarification_required=state.clarification_required,
                last_failure=state.last_failure,
                started_at=state.started_at,
                completed_at=completed_at,
                updated_at=now,
                status=status,
                location=location,
                github_issue=state.github_issue,
                github_repo=state.github_repo,
            )
            conn.commit()

    def record_artifact_write(
        self,
        *,
        task_name: str,
        name: str,
        content: str,
        stage: str | None = None,
    ) -> None:
        """Write/update artifact content in DB (canonical storage)."""
        if not self._is_indexable_artifact_name(name):
            return

        with self._connect() as conn:
            self._ensure_task_row(conn, task_name)
            self._upsert_artifact_conn(
                conn,
                task_name=task_name,
                name=name,
                content=content,
                stage=stage,
            )
            conn.commit()

        if self._is_mirrored_artifact(name):
            self._write_mirror_artifact_file(task_name=task_name, name=name, content=content)
        else:
            # Enforce DB canonical storage by removing legacy file mirrors.
            self._delete_legacy_artifact_file(task_name, name)

    def record_artifact_delete(self, *, task_name: str, name: str) -> None:
        """Mark artifact as absent in DB."""
        if not self._is_indexable_artifact_name(name):
            return

        now = _now_iso()
        with self._connect() as conn:
            self._ensure_task_row(conn, task_name)
            conn.execute(
                """
                INSERT INTO artifacts (task_name, name, updated_at, is_present)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(task_name, name) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    is_present = 0
                """,
                (task_name, name, now),
            )
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_name = ?",
                (now, task_name),
            )
            conn.commit()

        if self._is_mirrored_artifact(name):
            self._delete_legacy_artifact_file(task_name, name)

    def artifact_exists(self, *, task_name: str, name: str) -> bool:
        """Return whether artifact exists (DB canonical, with legacy import fallback)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM artifacts WHERE task_name = ? AND name = ? AND is_present = 1",
                (task_name, name),
            ).fetchone()
            if row:
                return True

            migrated = self._migrate_legacy_artifact_conn(
                conn,
                task_name=task_name,
                name=name,
                delete_file=True,
            )
            if migrated:
                conn.commit()
            return migrated

    def read_artifact(self, *, task_name: str, name: str) -> str | None:
        """Read artifact content (DB canonical, with legacy import fallback)."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT content
                FROM artifacts
                WHERE task_name = ? AND name = ? AND is_present = 1
                """,
                (task_name, name),
            ).fetchone()
            if row:
                return str(row["content"])

            migrated = self._migrate_legacy_artifact_conn(
                conn,
                task_name=task_name,
                name=name,
                delete_file=True,
            )
            if not migrated:
                return None

            conn.commit()
            row2 = conn.execute(
                """
                SELECT content
                FROM artifacts
                WHERE task_name = ? AND name = ? AND is_present = 1
                """,
                (task_name, name),
            ).fetchone()
            return str(row2["content"]) if row2 else None

    def delete_artifact(self, *, task_name: str, name: str) -> bool:
        """Delete artifact from canonical store (and remove any legacy file)."""
        content = self.read_artifact(task_name=task_name, name=name)
        legacy_deleted = self._delete_legacy_artifact_file(task_name, name)
        if content is None and not legacy_deleted:
            return False

        self.record_artifact_delete(task_name=task_name, name=name)
        return True

    def archive_artifact(self, *, task_name: str, name: str, archive_name: str) -> bool:
        """Archive artifact content to another artifact and delete source."""
        content = self.read_artifact(task_name=task_name, name=name)
        if content is None:
            return False

        existing_archive = self.read_artifact(task_name=task_name, name=archive_name)
        if existing_archive:
            merged = f"{existing_archive}\n\n---\n\n{content}"
        else:
            merged = content

        self.record_artifact_write(task_name=task_name, name=archive_name, content=merged)
        self.record_artifact_delete(task_name=task_name, name=name)
        return True

    def list_task_artifacts(self, *, task_name: str) -> list[str]:
        """List present artifact names for a task."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM artifacts
                WHERE task_name = ? AND is_present = 1
                ORDER BY name COLLATE NOCASE
                """,
                (task_name,),
            ).fetchall()
        return [str(row["name"]) for row in rows]

    def append_task_log_line(
        self,
        *,
        task_name: str,
        line: str,
        line_type: str = "raw",
        logged_at: str | None = None,
    ) -> None:
        """Append one task log line to DB storage."""
        if not line:
            return

        now = logged_at or _now_iso()
        with self._connect() as conn:
            self._ensure_task_row(conn, task_name)
            conn.execute(
                """
                INSERT INTO task_logs (task_name, logged_at, line_type, line)
                VALUES (?, ?, ?, ?)
                """,
                (task_name, now, line_type or "raw", line),
            )
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_name = ?",
                (now, task_name),
            )
            conn.commit()

    def append_task_log_lines(
        self,
        *,
        task_name: str,
        lines: list[str],
        line_type: str = "raw",
        logged_at: str | None = None,
    ) -> None:
        """Append multiple task log lines in one transaction."""
        filtered = [line for line in lines if line]
        if not filtered:
            return

        now = logged_at or _now_iso()
        with self._connect() as conn:
            self._ensure_task_row(conn, task_name)
            conn.executemany(
                """
                INSERT INTO task_logs (task_name, logged_at, line_type, line)
                VALUES (?, ?, ?, ?)
                """,
                [(task_name, now, line_type or "raw", line) for line in filtered],
            )
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_name = ?",
                (now, task_name),
            )
            conn.commit()

    def list_task_log_lines(
        self,
        *,
        task_name: str,
        since_id: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """List task log lines from DB, ordered by insertion id."""
        capped_limit = max(1, min(limit, 5000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, logged_at, line_type, line
                FROM task_logs
                WHERE task_name = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (task_name, since_id, capped_limit),
            ).fetchall()

        return [
            {
                "id": int(row["id"]),
                "logged_at": str(row["logged_at"]),
                "line_type": str(row["line_type"]),
                "line": str(row["line"]),
            }
            for row in rows
        ]

    def mark_task_status(
        self,
        *,
        task_name: str,
        status: str,
        location: Path | str | None = None,
        completed_at: str | None = None,
    ) -> None:
        """Update status and location for task row."""
        normalized = status.strip().lower()
        if normalized not in {"active", "done", "archived", "deleted"}:
            raise ValueError(f"Invalid task index status: {status}")

        if location is None:
            if normalized == "done":
                resolved = get_done_dir() / task_name
            elif normalized == "archived":
                resolved = get_tasks_dir() / ".archive" / task_name
            elif normalized == "deleted":
                resolved = Path("")
            else:
                resolved = get_tasks_dir() / task_name
        elif isinstance(location, Path):
            resolved = location
        else:
            resolved = Path(location)

        loc = "" if normalized == "deleted" else self._rel_path(resolved)
        now = _now_iso()
        completed_value = completed_at
        if not completed_value and normalized in {"done", "archived"}:
            completed_value = now

        with self._connect() as conn:
            self._ensure_task_row(conn, task_name)
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, location = ?, updated_at = ?,
                    completed_at = COALESCE(completed_at, ?)
                WHERE task_name = ?
                """,
                (normalized, loc, now, completed_value, task_name),
            )
            conn.commit()

    def mark_task_deleted(self, *, task_name: str) -> None:
        """Mark a task as deleted in task index."""
        self.mark_task_status(task_name=task_name, status="deleted", location="")

    def list_tasks(self, statuses: tuple[str, ...] = ("active",)) -> list[tuple[str, str, str, str]]:
        """List tasks for statuses, returning tuples for table display."""
        if not statuses:
            return []

        normalized = tuple(s.strip().lower() for s in statuses)
        placeholders = ",".join("?" for _ in normalized)
        query = (
            "SELECT task_name, stage, task_type, task_description "
            f"FROM tasks WHERE status IN ({placeholders}) "
            "ORDER BY task_name COLLATE NOCASE"
        )

        with self._connect() as conn:
            rows = conn.execute(query, normalized).fetchall()

        out: list[tuple[str, str, str, str]] = []
        for row in rows:
            desc = str(row["task_description"] or "")
            out.append(
                (
                    str(row["task_name"]),
                    str(row["stage"]),
                    str(row["task_type"]),
                    desc[:50],
                )
            )
        return out

    def check_integrity(self) -> dict[str, Any]:
        """Run SQLite integrity and foreign-key checks on the database.

        Returns a dict with ``ok`` bool and detail fields.
        """
        result: dict[str, Any] = {
            "ok": True,
            "exists": self.db_path.exists(),
            "db_path": str(self.db_path),
            "integrity_check": "ok",
            "foreign_key_errors": 0,
            "error": None,
        }
        if not self.db_path.exists():
            result["ok"] = False
            result["error"] = "database file does not exist"
            return result

        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            # Quick integrity check (stops after first error).
            integrity = conn.execute("PRAGMA integrity_check(1)").fetchone()
            integrity_val = str(integrity[0]) if integrity else "unknown"
            result["integrity_check"] = integrity_val
            if integrity_val != "ok":
                result["ok"] = False

            fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            result["foreign_key_errors"] = len(fk_errors)
            if fk_errors:
                result["ok"] = False

            conn.close()
        except sqlite3.DatabaseError as exc:
            result["ok"] = False
            result["error"] = str(exc)

        return result

    def get_stats(self) -> TaskIndexStats:
        """Get index summary stats."""
        with self._connect() as conn:
            total_tasks = int(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
            total_artifacts = int(
                conn.execute("SELECT COUNT(*) FROM artifacts WHERE is_present = 1").fetchone()[0]
            )
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
            ).fetchall()

        by_status = {str(row["status"]): int(row["n"]) for row in rows}
        return TaskIndexStats(
            db_path=self.db_path,
            total_tasks=total_tasks,
            total_artifacts=total_artifacts,
            tasks_by_status=by_status,
        )
