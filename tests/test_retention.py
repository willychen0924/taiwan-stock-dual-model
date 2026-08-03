from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from value_screener.retention import cleanup_dated_directories, iter_expired_dated_directories  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
