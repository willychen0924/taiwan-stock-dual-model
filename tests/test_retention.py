from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.retention import (  # noqa: E402
    cleanup_dated_directories,
    cleanup_dated_directories_by_root,
    iter_expired_dated_directories,
)


class RetentionTests(unittest.TestCase):
    def test_iter_expired_dated_directories_only_matches_old_date_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["2026-07-15", "2026-07-21", "2026-07-27", "latest", "misc-output"]:
                (root / name).mkdir()

            expired = iter_expired_dated_directories(root, as_of=date(2026, 7, 27), keep_days=7)

            self.assertEqual([path.name for path in expired], ["2026-07-15"])

    def test_cleanup_dated_directories_removes_only_expired_date_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dated_old = root / "2026-07-15"
            dated_keep = root / "2026-07-21"
            latest = root / "latest"
            for path in [dated_old, dated_keep, latest]:
                path.mkdir()

            deleted = cleanup_dated_directories([root], as_of=date(2026, 7, 27), keep_days=7)

            self.assertEqual([path.name for path in deleted], ["2026-07-15"])
            self.assertFalse(dated_old.exists())
            self.assertTrue(dated_keep.exists())
            self.assertTrue(latest.exists())

    def test_cleanup_supports_independent_retention_by_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            outputs = root / "outputs"
            qa = root / "qa"
            for parent in [reports, outputs, qa]:
                for name in ["2026-07-10", "2026-07-20", "2026-07-28", "latest"]:
                    (parent / name).mkdir(parents=True, exist_ok=True)

            deleted = cleanup_dated_directories_by_root(
                {reports: 14, outputs: 30, qa: 7},
                as_of=date(2026, 8, 3),
            )

            self.assertEqual(
                {(path.parent.name, path.name) for path in deleted},
                {
                    ("reports", "2026-07-10"),
                    ("reports", "2026-07-20"),
                    ("qa", "2026-07-10"),
                    ("qa", "2026-07-20"),
                },
            )
            self.assertFalse((reports / "2026-07-20").exists())
            self.assertTrue((outputs / "2026-07-10").exists())
            self.assertTrue((qa / "2026-07-28").exists())

    def test_dry_run_does_not_delete_expired_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "2026-07-10"
            old.mkdir()

            matched = cleanup_dated_directories_by_root(
                {root: 7},
                as_of=date(2026, 8, 3),
                dry_run=True,
            )

            self.assertEqual(matched, [old])
            self.assertTrue(old.exists())


if __name__ == "__main__":
    unittest.main()
