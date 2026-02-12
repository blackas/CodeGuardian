"""Tests for github_client module."""

from unittest.mock import MagicMock, patch, call
import logging

import pytest
from github import GithubException
from github.GithubException import UnknownObjectException

from src.github_client import GitHubClient
from src.platform_protocol import (
    CodeReviewPlatform,
    PlatformContext,
    PlatformFile,
)


def _make_event_data(
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
                "ref": "main",
                "repo": {"full_name": base_repo},
            },
        },
        "repository": {
            "full_name": "owner/repo",
        },
    }


@pytest.fixture
def event_data() -> dict:
    """Standard same-repo event payload."""
    return _make_event_data()


@pytest.fixture
def fork_event_data() -> dict:
    """Fork event payload (head != base repo)."""
    return _make_event_data(head_repo="contributor/repo")


@pytest.fixture
def mock_github(event_data: dict):
    """Patch PyGithub and return (client, mock_pr, mock_repo)."""
    with patch("src.github_client.Github") as MockGithub:
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        MockGithub.return_value.get_repo.return_value = mock_repo

        client = GitHubClient(
            token="fake-token",
            repo_name="owner/repo",
            event_data=event_data,
        )
        yield client, mock_pr, mock_repo


class TestGetContext:
    """Tests for GitHubClient.get_context."""

    def test_get_context_returns_platform_context(self, mock_github, event_data):
        """get_context returns PlatformContext with correct fields."""
        client, _, _ = mock_github

        context = client.get_context()

        assert isinstance(context, PlatformContext)
        assert context.number == 42
        assert context.title == "Add feature X"
        assert context.description == "This PR adds feature X."
        assert context.head_sha == "abc123def456"
        assert context.repo_identifier == "owner/repo"


class TestGetFiles:
    """Tests for GitHubClient.get_files."""

    def test_get_files_returns_platform_files(self, mock_github):
        """get_files converts PR files to PlatformFile objects."""
        client, mock_pr, _ = mock_github

        mock_file = MagicMock()
        mock_file.filename = "src/main.py"
        mock_file.patch = "@@ -1,2 +1,3 @@\n ctx\n+new"
        mock_file.additions = 1
        mock_file.deletions = 0
        mock_pr.get_files.return_value = [mock_file]

        files = client.get_files()

        assert len(files) == 1
        assert isinstance(files[0], PlatformFile)
        assert files[0].filename == "src/main.py"
        assert files[0].patch == "@@ -1,2 +1,3 @@\n ctx\n+new"
        assert files[0].additions == 1
        assert files[0].deletions == 0


class TestIsFork:
    """Tests for GitHubClient.is_fork."""

    def test_is_fork_detects_fork(self, fork_event_data):
        """is_fork returns True when head repo differs from base repo."""
        with patch("src.github_client.Github"):
            client = GitHubClient(
                token="fake-token",
                repo_name="owner/repo",
                event_data=fork_event_data,
            )
        assert client.is_fork() is True

    def test_is_fork_same_repo(self, mock_github):
        """is_fork returns False when head repo matches base repo."""
        client, _, _ = mock_github
        assert client.is_fork() is False


class TestPostReviewComments:
    """Tests for GitHubClient.post_review_comments."""

    def test_post_review_comments_batch(self, mock_github):
        """Batch review posts comments with side=RIGHT."""
        client, mock_pr, _ = mock_github
        last_commit = MagicMock()
        mock_pr.get_commits.return_value = [MagicMock(), last_commit]

        comments = [
            {"path": "src/main.py", "body": "Fix this", "line": 10},
            {"path": "src/utils.py", "body": "Rename this", "line": 5},
        ]

        client.post_review_comments(comments, "Review summary")

        mock_pr.create_review.assert_called_once()
        call_kwargs = mock_pr.create_review.call_args
        review_comments = call_kwargs.kwargs["comments"]
        assert len(review_comments) == 2
        for comment in review_comments:
            assert comment["side"] == "RIGHT"
        assert call_kwargs.kwargs["event"] == "COMMENT"
        assert call_kwargs.kwargs["body"] == "Review summary"

    def test_post_review_comments_chunks_at_30(self, mock_github):
        """Comments are chunked at 30 per create_review call."""
        client, mock_pr, _ = mock_github
        last_commit = MagicMock()
        mock_pr.get_commits.return_value = [MagicMock(), last_commit]

        comments = [
            {"path": f"file{i}.py", "body": f"Comment {i}", "line": i + 1}
            for i in range(50)
        ]

        client.post_review_comments(comments, "Big review")

        assert mock_pr.create_review.call_count == 2
        first_call = mock_pr.create_review.call_args_list[0]
        second_call = mock_pr.create_review.call_args_list[1]
        assert len(first_call.kwargs["comments"]) == 30
        assert len(second_call.kwargs["comments"]) == 20

    def test_post_review_comments_fallback_on_422(self, mock_github):
        """On 422 error, falls back to individual comment posting."""
        client, mock_pr, _ = mock_github
        last_commit = MagicMock()
        mock_pr.get_commits.return_value = [MagicMock(), last_commit]

        mock_pr.create_review.side_effect = GithubException(
            status=422,
            data={"message": "Validation Failed"},
            headers={},
        )

        comments = [
            {"path": "src/main.py", "body": "Fix this", "line": 10},
        ]

        client.post_review_comments(comments, "Summary")

        mock_pr.create_review_comment.assert_called_once()
        call_kwargs = mock_pr.create_review_comment.call_args.kwargs
        assert call_kwargs["path"] == "src/main.py"
        assert call_kwargs["body"] == "Fix this"
        assert call_kwargs["line"] == 10
        assert call_kwargs["side"] == "RIGHT"

    def test_post_review_comments_skips_invalid_line(self, mock_github, caplog):
        """Individual comment failure logs warning and skips."""
        client, mock_pr, _ = mock_github
        last_commit = MagicMock()
        mock_pr.get_commits.return_value = [MagicMock(), last_commit]

        mock_pr.create_review.side_effect = GithubException(
            status=422,
            data={"message": "Validation Failed"},
            headers={},
        )
        mock_pr.create_review_comment.side_effect = GithubException(
            status=422,
            data={"message": "Invalid line"},
            headers={},
        )

        comments = [
            {"path": "src/main.py", "body": "Fix this", "line": 999},
        ]

        with caplog.at_level(logging.WARNING):
            client.post_review_comments(comments, "Summary")

        assert "Skipping comment" in caplog.text

    def test_review_uses_comment_event(self, mock_github):
        """Review always uses event='COMMENT', never REQUEST_CHANGES."""
        client, mock_pr, _ = mock_github
        last_commit = MagicMock()
        mock_pr.get_commits.return_value = [MagicMock(), last_commit]

        comments = [
            {"path": "src/main.py", "body": "Note", "line": 1},
        ]

        client.post_review_comments(comments, "Just comments")

        call_kwargs = mock_pr.create_review.call_args.kwargs
        assert call_kwargs["event"] == "COMMENT"


class TestPostErrorComment:
    """Tests for GitHubClient.post_error_comment."""

    def test_post_error_comment(self, mock_github):
        """post_error_comment creates an issue comment."""
        client, mock_pr, _ = mock_github

        client.post_error_comment("Something went wrong")

        mock_pr.create_issue_comment.assert_called_once_with(
            body="Something went wrong"
        )


class TestGetFileContentSuccess:
    """get_file_content returns decoded content when file exists."""

    def test_returns_decoded_content(self, mock_github):
        client, _, mock_repo = mock_github

        mock_content_file = MagicMock()
        mock_content_file.decoded_content = b"# My Project"
        mock_repo.get_contents.return_value = mock_content_file

        result = client.get_file_content("AGENTS.md")

        assert result == "# My Project"
        mock_repo.get_contents.assert_called_once_with("AGENTS.md", ref="main")


class TestGetFileContentNotFound:
    """get_file_content returns None on 404."""

    def test_returns_none_on_404(self, mock_github):
        client, _, mock_repo = mock_github

        mock_repo.get_contents.side_effect = UnknownObjectException(
            404, {"message": "Not Found"}, {}
        )

        result = client.get_file_content("AGENTS.md")

        assert result is None


class TestGetFileContentError:
    """get_file_content returns None on generic exception."""

    def test_returns_none_on_generic_error(self, mock_github):
        client, _, mock_repo = mock_github

        mock_repo.get_contents.side_effect = Exception("Connection error")

        result = client.get_file_content("AGENTS.md")

        assert result is None
