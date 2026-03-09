"""Tests for Codex CLI-based code reviewer."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.ai_reviewer import ReviewComment, ReviewResponse
from src.codex_reviewer import CodexReviewer


class TestCodexReviewerBuildPrompt:
    def test_builds_prompt_with_file_info(self):
        reviewer = CodexReviewer()
        prompt = reviewer._build_prompt(
            file_path="src/app.py",
            patch="@@ -1 +1 @@\n-old\n+new",
            pr_title="Fix bug",
            pr_description="Fixes issue #1",
        )
        assert "src/app.py" in prompt
        assert "Fix bug" in prompt
        assert "@@ -1 +1 @@" in prompt

    def test_builds_prompt_with_project_context(self):
        reviewer = CodexReviewer(project_context="Django REST API")
        prompt = reviewer._build_prompt(
            file_path="src/app.py",
            patch="diff",
            pr_title="Test",
            pr_description="Test",
        )
        assert "Django REST API" in prompt


class TestCodexReviewerCallCodex:
    @patch("src.codex_reviewer.subprocess.run")
    def test_calls_codex_exec_and_parses_output(self, mock_run):
        review_data = {
            "comments": [
                {
                    "file_path": "src/app.py",
                    "line_number": 10,
                    "severity": "warning",
                    "category": "bug",
                    "comment": "Potential issue.",
                }
            ],
            "summary": "Found 1 issue.",
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(review_data),
            stderr="",
        )

        reviewer = CodexReviewer()
        result = reviewer.review_diff(
            file_path="src/app.py",
            patch="@@ -1 +1 @@\n-old\n+new",
            pr_title="Fix bug",
            pr_description="Fixes #1",
        )

        assert isinstance(result, ReviewResponse)
        assert len(result.comments) == 1
        assert result.comments[0].severity == "warning"
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "codex" in cmd[0]
        assert "exec" in cmd

    @patch("src.codex_reviewer.subprocess.run")
    def test_returns_empty_on_codex_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: something went wrong",
        )

        reviewer = CodexReviewer()
        result = reviewer.review_diff(
            file_path="src/app.py",
            patch="diff",
            pr_title="Test",
            pr_description="Test",
        )

        assert isinstance(result, ReviewResponse)
        assert result.comments == []
        assert "Error" in result.summary

    @patch("src.codex_reviewer.subprocess.run")
    def test_handles_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="codex", timeout=120)

        reviewer = CodexReviewer()
        result = reviewer.review_diff(
            file_path="src/app.py",
            patch="diff",
            pr_title="Test",
            pr_description="Test",
        )

        assert isinstance(result, ReviewResponse)
        assert result.comments == []
        assert "timed out" in result.summary.lower()


class TestCodexReviewerReviewFiles:
    @patch("src.codex_reviewer.subprocess.run")
    def test_aggregates_comments_from_multiple_files(self, mock_run):
        review_a = json.dumps({
            "comments": [{"file_path": "a.py", "line_number": 1, "severity": "error", "category": "bug", "comment": "Issue"}],
            "summary": "Review a",
        })
        review_b = json.dumps({
            "comments": [{"file_path": "b.py", "line_number": 5, "severity": "info", "category": "readability", "comment": "Note"}],
            "summary": "Review b",
        })
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=review_a, stderr=""),
            MagicMock(returncode=0, stdout=review_b, stderr=""),
        ]

        reviewer = CodexReviewer()
        comments = reviewer.review_files(
            files=[
                {"file_path": "a.py", "patch": "diff a"},
                {"file_path": "b.py", "patch": "diff b"},
            ],
            pr_title="Multi",
            pr_description="Test",
        )

        assert len(comments) == 2
        assert comments[0].file_path == "a.py"
        assert comments[1].file_path == "b.py"
