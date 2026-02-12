"""End-to-end integration tests for CodeGuardian dual-platform pipeline."""

import json
import os
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import github
import gitlab.exceptions

from src.review import main


SAMPLE_PATCH = (
    "@@ -1,3 +1,5 @@\n context\n+added_line_1\n+added_line_2\n context\n context"
)


class TestGithubEndToEnd:
    """Full GitHub pipeline: event.json -> OpenAI -> create_review."""

    @patch("src.github_client.Github")
    @patch("src.ai_reviewer.OpenAI")
    def test_github_end_to_end(self, mock_openai_cls, mock_github_cls):
        event_path = os.path.join(os.path.dirname(__file__), "fixtures", "event.json")

        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr
        mock_repo.get_contents.side_effect = github.UnknownObjectException(404, {}, {})

        mock_file = MagicMock()
        mock_file.filename = "src/main.py"
        mock_file.patch = SAMPLE_PATCH
        mock_file.additions = 2
        mock_file.deletions = 0
        mock_pr.get_files.return_value = [mock_file]

        last_commit = MagicMock()
        mock_pr.get_commits.return_value = [last_commit]

        mock_pr.head.repo.full_name = "owner/repo"
        mock_pr.base.repo.full_name = "owner/repo"

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        ai_response_content = json.dumps(
            {
                "comments": [
                    {
                        "file_path": "src/main.py",
                        "line_number": 2,
                        "severity": "warning",
                        "category": "readability",
                        "comment": "Consider a more descriptive name.",
                    }
                ],
                "summary": "One issue found.",
            }
        )
        mock_choice = MagicMock()
        mock_choice.message.content = ai_response_content
        mock_choice.message.refusal = None
        mock_choice.finish_reason = "stop"
        mock_openai.chat.completions.create.return_value = MagicMock(
            choices=[mock_choice]
        )

        env = {
            "GITHUB_EVENT_PATH": event_path,
            "GITHUB_TOKEN": "mock",
            "OPENAI_API_KEY": "real-key-triggers-openai-path",
        }
        with patch.dict(os.environ, env, clear=True):
            main()

        mock_pr.create_review.assert_called_once()
        call_kwargs = mock_pr.create_review.call_args.kwargs
        review_comments = call_kwargs["comments"]
        assert len(review_comments) == 1
        assert review_comments[0]["line"] == 2
        assert review_comments[0]["side"] == "RIGHT"
        assert "position" not in review_comments[0]


class TestGitlabEndToEnd:
    """Full GitLab pipeline: env vars -> OpenAI -> discussions.create."""

    @patch("src.gitlab_client.gitlab.Gitlab")
    @patch("src.ai_reviewer.OpenAI")
    def test_gitlab_end_to_end(self, mock_openai_cls, mock_gitlab_cls):
        mock_gl = MagicMock()
        mock_gitlab_cls.return_value = mock_gl

        mock_project = MagicMock()
        mock_gl.projects.get.return_value = mock_project
        mock_project.files.get.side_effect = gitlab.exceptions.GitlabGetError(
            "404 File Not Found"
        )

        mock_mr = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr
        mock_mr.iid = 42
        mock_mr.title = "Fix auth bug"
        mock_mr.description = "Token refresh fix"
        mock_mr.sha = "head_sha_abc"
        mock_mr.target_branch = "main"
        mock_mr.diff_refs = {
            "base_sha": "base000",
            "start_sha": "start111",
            "head_sha": "head_sha_abc",
        }
        mock_mr.changes.return_value = {
            "changes": [
                {
                    "new_path": "src/main.py",
                    "diff": SAMPLE_PATCH,
                },
            ]
        }

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        ai_response_content = json.dumps(
            {
                "comments": [
                    {
                        "file_path": "src/main.py",
                        "line_number": 2,
                        "severity": "error",
                        "category": "bug",
                        "comment": "Potential null dereference.",
                    }
                ],
                "summary": "One bug found.",
            }
        )
        mock_choice = MagicMock()
        mock_choice.message.content = ai_response_content
        mock_choice.message.refusal = None
        mock_choice.finish_reason = "stop"
        mock_openai.chat.completions.create.return_value = MagicMock(
            choices=[mock_choice]
        )

        env = {
            "CI_MERGE_REQUEST_IID": "42",
            "CI_PROJECT_ID": "1",
            "GITLAB_TOKEN": "mock",
            "OPENAI_API_KEY": "real-key-triggers-openai-path",
        }
        with patch.dict(os.environ, env, clear=True):
            main()

        mock_mr.discussions.create.assert_called_once()
        disc_arg = mock_mr.discussions.create.call_args[0][0]
        position = disc_arg["position"]
        assert position["base_sha"] == "base000"
        assert position["start_sha"] == "start111"
        assert position["head_sha"] == "head_sha_abc"
        assert position["position_type"] == "text"
        assert position["new_path"] == "src/main.py"
        assert position["new_line"] == 2

        mock_mr.notes.create.assert_called_once()
        summary_body = mock_mr.notes.create.call_args[0][0]["body"]
        assert "CodeGuardian Review" in summary_body


class TestGithubErrorPostsComment:
    """OpenAI error -> error comment posted on GitHub PR."""

    @patch("src.github_client.Github")
    @patch("src.ai_reviewer.OpenAI")
    def test_github_error_posts_comment(self, mock_openai_cls, mock_github_cls):
        event_path = os.path.join(os.path.dirname(__file__), "fixtures", "event.json")

        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_github_cls.return_value.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr
        mock_repo.get_contents.side_effect = github.UnknownObjectException(404, {}, {})

        mock_file = MagicMock()
        mock_file.filename = "src/main.py"
        mock_file.patch = SAMPLE_PATCH
        mock_file.additions = 2
        mock_file.deletions = 0
        mock_pr.get_files.return_value = [mock_file]

        mock_pr.head.repo.full_name = "owner/repo"
        mock_pr.base.repo.full_name = "owner/repo"

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = RuntimeError(
            "API connection failed"
        )

        env = {
            "GITHUB_EVENT_PATH": event_path,
            "GITHUB_TOKEN": "mock",
            "OPENAI_API_KEY": "real-key-triggers-openai-path",
        }
        with patch.dict(os.environ, env, clear=True):
            main()

        mock_pr.create_issue_comment.assert_called_once()
        error_body = mock_pr.create_issue_comment.call_args.kwargs["body"]
        assert "error" in error_body.lower()


class TestGitlabErrorPostsComment:
    """OpenAI error -> error comment posted as GitLab MR note."""

    @patch("src.gitlab_client.gitlab.Gitlab")
    @patch("src.ai_reviewer.OpenAI")
    def test_gitlab_error_posts_comment(self, mock_openai_cls, mock_gitlab_cls):
        mock_gl = MagicMock()
        mock_gitlab_cls.return_value = mock_gl

        mock_project = MagicMock()
        mock_gl.projects.get.return_value = mock_project
        mock_project.files.get.side_effect = gitlab.exceptions.GitlabGetError(
            "404 File Not Found"
        )

        mock_mr = MagicMock()
        mock_project.mergerequests.get.return_value = mock_mr
        mock_mr.iid = 42
        mock_mr.title = "Fix bug"
        mock_mr.description = "Desc"
        mock_mr.sha = "sha123"
        mock_mr.target_branch = "main"
        mock_mr.diff_refs = {
            "base_sha": "b",
            "start_sha": "s",
            "head_sha": "h",
        }
        mock_mr.changes.return_value = {
            "changes": [
                {
                    "new_path": "src/main.py",
                    "diff": SAMPLE_PATCH,
                },
            ]
        }

        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.side_effect = RuntimeError("API timeout")

        env = {
            "CI_MERGE_REQUEST_IID": "42",
            "CI_PROJECT_ID": "1",
            "GITLAB_TOKEN": "mock",
            "OPENAI_API_KEY": "real-key-triggers-openai-path",
        }
        with patch.dict(os.environ, env, clear=True):
            main()

        mock_mr.notes.create.assert_called_once()
        note_body = mock_mr.notes.create.call_args[0][0]["body"]
        assert "Error" in note_body or "error" in note_body.lower()


class TestNoPlatformDetectedExits:
    """No env vars -> sys.exit(1)."""

    def test_no_platform_detected_exits(self):
        env: dict[str, str] = {}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


class TestFullTestSuiteRunsClean:
    """Run full test suite via subprocess and verify 0 failures."""

    def test_full_test_suite_runs_clean(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/",
                "-v",
                "--tb=short",
                "--ignore=tests/test_integration.py",
            ],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(__file__)),
            timeout=120,
        )
        assert result.returncode == 0, (
            f"Test suite failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        last_line = result.stdout.strip().splitlines()[-1]
        assert "passed" in last_line
        assert "failed" not in last_line.lower()
