"""Tests for review module — main orchestrator with dual-platform auto-detection."""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.ai_reviewer import ReviewComment
from src.review import (
    build_summary,
    create_platform,
    format_comment_body,
    load_event_data,
    main,
    validate_comment_lines,
)


def _make_github_event_data(
    *,
    head_repo: str = "owner/repo",
    base_repo: str = "owner/repo",
) -> dict:
    """Build a minimal GitHub webhook event payload."""
    return {
        "action": "opened",
        "number": 42,
        "pull_request": {
            "number": 42,
            "title": "Add feature X",
            "body": "This PR adds feature X.",
            "head": {
                "sha": "abc123def456",
                "repo": {"full_name": head_repo},
            },
            "base": {
                "repo": {"full_name": base_repo},
            },
        },
        "repository": {
            "full_name": "owner/repo",
        },
    }


SAMPLE_PATCH = "@@ -1,3 +1,5 @@\n line1\n+added_line2\n+added_line3\n line4\n line5"


class TestCreatePlatformGithub:
    """test_create_platform_github — GITHUB_EVENT_PATH set -> GitHubClient."""

    @patch("src.review.GitHubClient")
    def test_creates_github_client_when_event_path_set(self, mock_github_cls):
        """When GITHUB_EVENT_PATH is set, create_platform returns a GitHubClient."""
        event_data = _make_github_event_data()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(event_data, f)
            event_path = f.name

        try:
            env = {
                "GITHUB_EVENT_PATH": event_path,
                "GITHUB_TOKEN": "ghp_test123",
            }
            with patch.dict(os.environ, env, clear=True):
                result = create_platform()

            mock_github_cls.assert_called_once_with(
                token="ghp_test123",
                repo_name="owner/repo",
                event_data=event_data,
            )
            assert result == mock_github_cls.return_value
        finally:
            os.unlink(event_path)


class TestCreatePlatformGitlab:
    """test_create_platform_gitlab — CI_MERGE_REQUEST_IID set -> GitLabClient."""

    @patch("src.review.GitLabClient")
    def test_creates_gitlab_client_when_mr_iid_set(self, mock_gitlab_cls):
        """When CI_MERGE_REQUEST_IID is set, create_platform returns a GitLabClient."""
        env = {
            "CI_MERGE_REQUEST_IID": "7",
            "CI_PROJECT_ID": "12345",
            "GITLAB_TOKEN": "glpat-test",
            "CI_SERVER_URL": "https://gitlab.example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            result = create_platform()

        mock_gitlab_cls.assert_called_once_with(
            token="glpat-test",
            project_id="12345",
            mr_iid=7,
            gitlab_url="https://gitlab.example.com",
        )
        assert result == mock_gitlab_cls.return_value


class TestCreatePlatformUnknown:
    """test_create_platform_unknown_exits — No env vars -> sys.exit(1)."""

    def test_exits_when_no_platform_detected(self):
        """When no platform env vars are set, sys.exit(1) is called."""
        env: dict[str, str] = {}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                create_platform()
            assert exc_info.value.code == 1


class TestMainEndToEndGithub:
    """test_main_end_to_end_github — Full pipeline, GitHub path."""

    @patch("src.review.AIReviewer")
    @patch("src.review.create_platform")
    def test_full_github_pipeline(self, mock_create_platform, mock_reviewer_cls):
        """Full pipeline: platform -> context -> files -> review -> post."""
        mock_platform = MagicMock()
        mock_create_platform.return_value = mock_platform

        mock_platform.is_fork.return_value = False
        mock_platform.get_context.return_value = MagicMock(
            title="Add feature",
            description="Adds X",
            head_sha="abc123",
        )

        mock_file = MagicMock()
        mock_file.filename = "src/app.py"
        mock_file.patch = SAMPLE_PATCH
        mock_file.additions = 2
        mock_file.deletions = 0
        mock_platform.get_files.return_value = [mock_file]

        mock_reviewer = MagicMock()
        mock_reviewer_cls.return_value = mock_reviewer
        mock_reviewer.review_files.return_value = [
            ReviewComment(
                file_path="src/app.py",
                line_number=2,
                severity="error",
                category="bug",
                comment="Potential bug here",
            ),
        ]

        env = {"OPENAI_API_KEY": "sk-test123"}
        with patch.dict(os.environ, env, clear=False):
            main()

        mock_platform.post_review_comments.assert_called_once()
        call_args = mock_platform.post_review_comments.call_args
        comments = call_args[0][0] if call_args[0] else call_args[1]["comments"]
        assert len(comments) == 1
        assert comments[0]["path"] == "src/app.py"
        assert comments[0]["line"] == 2


class TestMainEndToEndGitlab:
    """test_main_end_to_end_gitlab — Full pipeline, GitLab path."""

    @patch("src.review.AIReviewer")
    @patch("src.review.create_platform")
    def test_full_gitlab_pipeline(self, mock_create_platform, mock_reviewer_cls):
        """Full pipeline works identically for GitLab platform."""
        mock_platform = MagicMock()
        mock_create_platform.return_value = mock_platform

        mock_platform.is_fork.return_value = False
        mock_platform.get_context.return_value = MagicMock(
            title="Fix bug",
            description="Fixes Y",
            head_sha="def456",
        )

        mock_file = MagicMock()
        mock_file.filename = "lib/utils.ts"
        mock_file.patch = SAMPLE_PATCH
        mock_file.additions = 2
        mock_file.deletions = 0
        mock_platform.get_files.return_value = [mock_file]

        mock_reviewer = MagicMock()
        mock_reviewer_cls.return_value = mock_reviewer
        mock_reviewer.review_files.return_value = [
            ReviewComment(
                file_path="lib/utils.ts",
                line_number=3,
                severity="warning",
                category="readability",
                comment="Consider renaming",
            ),
        ]

        env = {"OPENAI_API_KEY": "sk-test456"}
        with patch.dict(os.environ, env, clear=False):
            main()

        mock_platform.post_review_comments.assert_called_once()


class TestForkPrExitsEarly:
    """test_fork_pr_exits_early — Fork -> exit 0, no OpenAI call."""

    @patch("src.review.AIReviewer")
    @patch("src.review.create_platform")
    def test_fork_skips_review(self, mock_create_platform, mock_reviewer_cls):
        """Fork PRs exit early without calling AI reviewer."""
        mock_platform = MagicMock()
        mock_create_platform.return_value = mock_platform
        mock_platform.is_fork.return_value = True
        mock_platform.get_context.return_value = MagicMock(
            title="Fork PR",
            description="From fork",
            head_sha="fork123",
        )

        env = {"OPENAI_API_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        mock_reviewer_cls.assert_not_called()


class TestNoReviewableFilesPostsSummary:
    """test_no_reviewable_files_posts_summary — All filtered -> summary only."""

    @patch("src.review.AIReviewer")
    @patch("src.review.create_platform")
    def test_no_reviewable_files(self, mock_create_platform, mock_reviewer_cls):
        """When all files are filtered out, post error comment and exit."""
        mock_platform = MagicMock()
        mock_create_platform.return_value = mock_platform
        mock_platform.is_fork.return_value = False
        mock_platform.get_context.return_value = MagicMock(
            title="Update README",
            description="Docs only",
            head_sha="readme123",
        )

        # Only a .md file (not reviewable)
        mock_file = MagicMock()
        mock_file.filename = "README.md"
        mock_file.patch = "@@ -1,1 +1,2 @@\n line1\n+line2"
        mock_file.additions = 1
        mock_file.deletions = 0
        mock_platform.get_files.return_value = [mock_file]

        env = {"OPENAI_API_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        mock_platform.post_error_comment.assert_called_once()
        assert "No reviewable files" in mock_platform.post_error_comment.call_args[0][0]
        mock_reviewer_cls.assert_not_called()


class TestInvalidLineCommentsFiltered:
    """test_invalid_line_comments_filtered — Line 999 -> filtered out."""

    @patch("src.review.AIReviewer")
    @patch("src.review.create_platform")
    def test_invalid_line_filtered(self, mock_create_platform, mock_reviewer_cls):
        """Comments with invalid line numbers are filtered out."""
        mock_platform = MagicMock()
        mock_create_platform.return_value = mock_platform
        mock_platform.is_fork.return_value = False
        mock_platform.get_context.return_value = MagicMock(
            title="Test",
            description="Test",
            head_sha="test123",
        )

        mock_file = MagicMock()
        mock_file.filename = "src/app.py"
        mock_file.patch = SAMPLE_PATCH
        mock_file.additions = 2
        mock_file.deletions = 0
        mock_platform.get_files.return_value = [mock_file]

        mock_reviewer = MagicMock()
        mock_reviewer_cls.return_value = mock_reviewer
        mock_reviewer.review_files.return_value = [
            ReviewComment(
                file_path="src/app.py",
                line_number=2,
                severity="error",
                category="bug",
                comment="Valid comment on line 2",
            ),
            ReviewComment(
                file_path="src/app.py",
                line_number=999,
                severity="warning",
                category="readability",
                comment="Hallucinated line",
            ),
        ]

        env = {"OPENAI_API_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=False):
            main()

        call_args = mock_platform.post_review_comments.call_args
        comments = call_args[0][0] if call_args[0] else call_args[1]["comments"]
        # Only the valid comment (line 2) should remain
        assert len(comments) == 1
        assert comments[0]["line"] == 2


class TestErrorPostsErrorComment:
    """test_error_posts_error_comment — OpenAI error -> error comment."""

    @patch("src.review.AIReviewer")
    @patch("src.review.create_platform")
    def test_exception_posts_error(self, mock_create_platform, mock_reviewer_cls):
        """When an exception occurs, an error comment is posted."""
        mock_platform = MagicMock()
        mock_create_platform.return_value = mock_platform
        mock_platform.is_fork.return_value = False
        mock_platform.get_context.return_value = MagicMock(
            title="Test",
            description="Test",
            head_sha="test123",
        )

        mock_file = MagicMock()
        mock_file.filename = "src/app.py"
        mock_file.patch = SAMPLE_PATCH
        mock_file.additions = 2
        mock_file.deletions = 0
        mock_platform.get_files.return_value = [mock_file]

        mock_reviewer = MagicMock()
        mock_reviewer_cls.return_value = mock_reviewer
        mock_reviewer.review_files.side_effect = RuntimeError("OpenAI API is down")

        env = {"OPENAI_API_KEY": "sk-test"}
        with patch.dict(os.environ, env, clear=False):
            main()

        mock_platform.post_error_comment.assert_called_once()
        error_msg = mock_platform.post_error_comment.call_args[0][0]
        assert "OpenAI API is down" in error_msg


class TestValidateCommentLines:
    """test_validate_comment_lines_filters_hallucinated — Invalid line -> removed."""

    def test_filters_invalid_lines(self):
        """Comments with lines not in the patch are removed."""
        comments = [
            ReviewComment(
                file_path="src/app.py",
                line_number=2,
                severity="error",
                category="bug",
                comment="Valid",
            ),
            ReviewComment(
                file_path="src/app.py",
                line_number=999,
                severity="info",
                category="readability",
                comment="Hallucinated",
            ),
        ]
        # SAMPLE_PATCH valid lines: 1, 2, 3, 4, 5
        file_patches = {"src/app.py": SAMPLE_PATCH}
        result = validate_comment_lines(comments, file_patches)
        assert len(result) == 1
        assert result[0].line_number == 2


class TestFormatCommentBody:
    """test_format_comment_body — Format verification."""

    def test_formats_correctly(self):
        """Comment body formatted as **[severity] [category]**: comment."""
        comment = ReviewComment(
            file_path="src/app.py",
            line_number=10,
            severity="error",
            category="bug",
            comment="Null pointer dereference",
        )
        result = format_comment_body(comment)
        assert result == "**[error] [bug]**: Null pointer dereference"

    def test_formats_warning(self):
        """Warning severity formatted correctly."""
        comment = ReviewComment(
            file_path="lib/utils.ts",
            line_number=5,
            severity="warning",
            category="performance",
            comment="O(n^2) loop detected",
        )
        result = format_comment_body(comment)
        assert result == "**[warning] [performance]**: O(n^2) loop detected"


class TestBuildSummary:
    """test_build_summary_counts_severity — severity breakdown."""

    def test_counts_severities(self):
        """Summary includes correct severity breakdown."""
        comments = [
            ReviewComment(
                file_path="a.py",
                line_number=1,
                severity="error",
                category="bug",
                comment="err1",
            ),
            ReviewComment(
                file_path="a.py",
                line_number=2,
                severity="error",
                category="bug",
                comment="err2",
            ),
            ReviewComment(
                file_path="b.py",
                line_number=3,
                severity="warning",
                category="readability",
                comment="warn1",
            ),
        ]
        result = build_summary(comments)
        assert "3 issues" in result
        assert "2 errors" in result
        assert "1 warning" in result
        assert "CodeGuardian" in result

    def test_empty_comments(self):
        """Empty comments list produces summary with 0 issues."""
        result = build_summary([])
        assert "0 issues" in result
