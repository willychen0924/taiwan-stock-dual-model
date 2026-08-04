from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )


class GithubPagesPublishTests(unittest.TestCase):
    def test_publisher_pushes_only_latest_html_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            project = temp / "project"
            remote = temp / "remote.git"
            checkout = temp / "checkout"
            (project / "reports" / "latest").mkdir(parents=True)
            (project / "reports" / "weekly" / "latest").mkdir(parents=True)
            (project / "docs").mkdir()
            (project / "reports" / "latest" / "index.html").write_text("daily", encoding="utf-8")
            (project / "reports" / "weekly" / "latest" / "index.html").write_text(
                "weekly", encoding="utf-8"
            )
            (project / "docs" / "github_pages_index.html").write_text("root", encoding="utf-8")
            (project / ".env").write_text("FINMIND_TOKEN=secret", encoding="utf-8")

            run("git", "init", "--bare", str(remote), cwd=temp)
            run("git", "init", cwd=project)
            run("git", "config", "user.name", "Test Bot", cwd=project)
            run("git", "config", "user.email", "test@example.com", cwd=project)
            run("git", "remote", "add", "origin", str(remote), cwd=project)

            env = {**os.environ, "PROJECT_ROOT": str(project)}
            first = run(
                "zsh",
                str(ROOT / "scripts" / "publish_github_pages.sh"),
                "2026-08-04",
                cwd=project,
                env=env,
            )
            self.assertIn("已發布日報與週報", first.stdout)

            run("git", "clone", "--quiet", "--branch", "gh-pages", str(remote), str(checkout), cwd=temp)
            published = sorted(
                path.relative_to(checkout).as_posix()
                for path in checkout.rglob("*")
                if path.is_file() and ".git" not in path.parts
            )
            self.assertEqual(
                published,
                [
                    ".nojekyll",
                    "index.html",
                    "reports/latest/index.html",
                    "reports/weekly/latest/index.html",
                ],
            )
            self.assertEqual((checkout / "reports" / "latest" / "index.html").read_text(), "daily")
            self.assertFalse((checkout / ".env").exists())

            second = run(
                "zsh",
                str(ROOT / "scripts" / "publish_github_pages.sh"),
                "2026-08-04",
                cwd=project,
                env=env,
            )
            self.assertIn("內容沒有變更", second.stdout)


if __name__ == "__main__":
    unittest.main()
