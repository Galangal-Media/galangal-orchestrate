"""Model-free tests for mistake-tracking wiring (no embedding model invoked)."""

import time
from unittest.mock import MagicMock, patch

from galangal.mistakes import (
    RECENCY_HALF_LIFE_DAYS,
    Mistake,
    MistakeTracker,
    log_mistake,
)


def _mistake(occ, age_days, mid=1):
    ts = int(time.time()) - int(age_days * 86400)
    return Mistake(mid, "d", "f", "DEV", [], occ, "t", ts, [])


class TestRelevanceScore:
    def test_recency_decay(self):
        t = MistakeTracker.__new__(MistakeTracker)
        fresh = _mistake(occ=4, age_days=0)
        one_halflife = _mistake(occ=4, age_days=RECENCY_HALF_LIFE_DAYS)
        assert abs(t._relevance_score(fresh) - 4.0) < 1e-3
        assert abs(t._relevance_score(one_halflife) - 2.0) < 1e-3

    def test_stale_high_count_can_lose_to_fresh(self):
        t = MistakeTracker.__new__(MistakeTracker)
        fresh = _mistake(occ=3, age_days=0)
        very_stale = _mistake(occ=10, age_days=5 * RECENCY_HALF_LIFE_DAYS)  # *1/32
        assert t._relevance_score(fresh) > t._relevance_score(very_stale)


class TestGetChangedFiles:
    def test_parses_git_output(self):
        from galangal.core import git_utils

        with patch.object(git_utils, "run_command", return_value=(0, "a.py\nb.py\n", "")):
            assert git_utils.get_changed_files() == ["a.py", "b.py"]

    def test_returns_empty_on_error(self):
        from galangal.core import git_utils

        with patch.object(git_utils, "run_command", return_value=(1, "", "fatal")):
            assert git_utils.get_changed_files() == []


class TestLogMistakeFileWiring:
    def test_derives_files_when_none(self):
        fake_tracker = MagicMock()
        with (
            patch("galangal.mistakes.get_tracker", return_value=fake_tracker),
            patch("galangal.core.git_utils.get_changed_files", return_value=["x.py"]),
        ):
            log_mistake("Null deref. Fix it.", stage="DEV", task_name="t")

        _, kwargs = fake_tracker.log.call_args
        assert kwargs["files"] == ["x.py"]
        assert kwargs["stage"] == "DEV"

    def test_explicit_files_are_passed_through(self):
        fake_tracker = MagicMock()
        with patch("galangal.mistakes.get_tracker", return_value=fake_tracker):
            log_mistake("oops", stage="TEST", task_name="t", files=["given.py"])

        _, kwargs = fake_tracker.log.call_args
        assert kwargs["files"] == ["given.py"]


class TestPruning:
    def _tracker(self, tmp_path):
        import galangal.mistakes as m

        t = m.MistakeTracker(db_path=tmp_path / "mistakes.db")
        _ = t.conn  # init tables
        return t

    def _insert(self, t, desc, occ, ts):
        t.conn.execute(
            "INSERT INTO mistakes (description,feedback,stage,file_patterns,occurrence_count,"
            "last_task,last_timestamp,example_tasks,embedding) VALUES (?,?,?,?,?,?,?,?,?)",
            [desc, "f", "DEV", "[]", occ, "task", ts, "[]", None],
        )

    def test_prune_drops_stale_rare_keeps_frequent_and_fresh(self, tmp_path):
        import time

        import galangal.mistakes as m

        t = self._tracker(tmp_path)
        now = int(time.time())
        old = now - (m.PRUNE_AGE_DAYS + 10) * 86400
        self._insert(t, "stale-rare", 1, old)
        self._insert(t, "old-frequent", 9, old)
        self._insert(t, "fresh", 1, now)
        t.conn.commit()

        t._prune()

        rows = {r[0] for r in t.conn.execute("SELECT description FROM mistakes").fetchall()}
        assert "stale-rare" not in rows
        assert {"old-frequent", "fresh"} <= rows

    def test_prune_enforces_hard_cap(self, tmp_path):
        import time

        import galangal.mistakes as m

        t = self._tracker(tmp_path)
        now = int(time.time())
        for i in range(m.MAX_MISTAKES + 25):
            self._insert(t, f"m{i}", 5, now)  # all fresh+frequent (no stale path)
        t.conn.commit()

        t._prune()

        total = t.conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0]
        assert total == m.MAX_MISTAKES
