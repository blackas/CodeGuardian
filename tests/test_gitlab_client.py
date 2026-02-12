"""Tests for gitlab_client module."""

import pytest
from unittest.mock import MagicMock, patch

from gitlab.exceptions import GitlabGetError

from src.gitlab_client import GitLabClient
from src.platform_protocol import PlatformContext, PlatformFile, CodeReviewPlatform


@pytest.fixture
def mock_mr():
    """Create a mock MergeRequest with standard attributes."""
    mr = MagicMock()
    mr.iid = 42
    mr.title = "Fix authentication bug"
    mr.description = "Resolves issue #99 with token refresh"
    mr.sha = "head_sha_abc123"
    mr.target_branch = "main"
    mr.diff_refs = {
        "base_sha": "base_sha_000",
        "start_sha": "start_sha_111",
        "head_sha": "head_sha_abc123",
    }
    mr.changes.return_value = {
        "changes": [
            {
                "new_path": "src/auth.py",
                "diff": "@@ -1,3 +1,5 @@\n context\n+added line 1\n+added line 2\n-removed line\n context\n",
            },
            {
                "new_path": "README.md",
                "diff": "@@ -10,2 +10,3 @@\n context\n+new doc line\n",
            },
        ]
    }
    return mr


@pytest.fixture
def mock_project(mock_mr):
    """Create a mock Project that returns mock_mr."""
    project = MagicMock()
    project.id = 12345
    project.mergerequests.get.return_value = mock_mr
    return project


@pytest.fixture
def mock_gitlab(mock_project):
    """Create a mock Gitlab instance that returns mock_project."""
    gl = MagicMock()
    gl.projects.get.return_value = mock_project
    return gl


@pytest.fixture
def client(mock_gitlab):
    """Create GitLabClient with mocked python-gitlab."""
    with patch("src.gitlab_client.gitlab.Gitlab", return_value=mock_gitlab):
        return GitLabClient(
            token="glpat-test-token",
            project_id=12345,
            mr_iid=42,
        )


class TestGetContext:
    """Tests for get_context method."""

    def test_get_context_returns_platform_context(self, client, mock_mr):
        """get_context returns PlatformContext with correct MR attributes."""
        context = client.get_context()

        assert isinstance(context, PlatformContext)
        assert context.number == 42
        assert context.title == "Fix authentication bug"
        assert context.description == "Resolves issue #99 with token refresh"
        assert context.head_sha == "head_sha_abc123"
        assert context.repo_identifier == "12345"


class TestGetFiles:
    """Tests for get_files method."""

    def test_get_files_returns_platform_files(self, client, mock_mr):
        """get_files returns list of PlatformFile with correct counts."""
        files = client.get_files()

        assert len(files) == 2
        assert all(isinstance(f, PlatformFile) for f in files)

        # First file: 2 additions (+), 1 deletion (-)
        assert files[0].filename == "src/auth.py"
        assert files[0].additions == 2
        assert files[0].deletions == 1
        assert files[0].patch is not None

        # Second file: 1 addition, 0 deletions
        assert files[1].filename == "README.md"
        assert files[1].additions == 1
        assert files[1].deletions == 0


class TestIsFork:
    """Tests for is_fork method."""

    def test_is_fork_returns_false(self, client):
        """is_fork always returns False for GitLab v1."""
        assert client.is_fork() is False


class TestPostReviewComments:
    """Tests for post_review_comments method."""

    def test_post_review_comments_creates_discussions(self, client, mock_mr):
        """post_review_comments creates a discussion for each comment."""
        comments = [
            {
                "path": "src/auth.py",
                "body": "Consider using constant time compare",
                "line": 10,
            },
            {"path": "README.md", "body": "Typo in docs", "line": 5},
        ]
        summary = "Overall: 2 issues found"

        client.post_review_comments(comments, summary)

        assert mock_mr.discussions.create.call_count == 2

    def test_post_review_comments_uses_diff_refs(self, client, mock_mr):
        """Discussions use correct diff_refs from MR."""
        comments = [
            {"path": "src/auth.py", "body": "Issue here", "line": 15},
        ]

        client.post_review_comments(comments, "Summary")

        call_args = mock_mr.discussions.create.call_args[0][0]
        position = call_args["position"]
        assert position["base_sha"] == "base_sha_000"
        assert position["start_sha"] == "start_sha_111"
        assert position["head_sha"] == "head_sha_abc123"
        assert position["position_type"] == "text"
        assert position["new_path"] == "src/auth.py"
        assert position["new_line"] == 15

    def test_post_review_comments_posts_summary_note(self, client, mock_mr):
        """post_review_comments posts summary as MR note."""
        comments = [
            {"path": "src/auth.py", "body": "Fix this", "line": 1},
        ]
        summary = "Review complete: 1 issue"

        client.post_review_comments(comments, summary)

        mock_mr.notes.create.assert_called_once_with(
            {"body": "Review complete: 1 issue"}
        )

    def test_post_review_comments_skips_failed_inline(self, client, mock_mr):
        """GitlabCreateError on inline comment is logged and skipped."""
        from gitlab.exceptions import GitlabCreateError

        # First discussion fails, second succeeds
        mock_mr.discussions.create.side_effect = [
            GitlabCreateError("400: Line is not part of the diff"),
            MagicMock(),
        ]
        comments = [
            {"path": "src/auth.py", "body": "Bad line ref", "line": 999},
            {"path": "README.md", "body": "Good comment", "line": 5},
        ]

        # Should not raise
        client.post_review_comments(comments, "Summary")

        # Both attempted, summary still posted
        assert mock_mr.discussions.create.call_count == 2
        mock_mr.notes.create.assert_called_once_with({"body": "Summary"})


class TestPostErrorComment:
    """Tests for post_error_comment method."""

    def test_post_error_comment(self, client, mock_mr):
        """post_error_comment posts formatted error as MR note."""
        client.post_error_comment("API rate limit exceeded")

        mock_mr.notes.create.assert_called_once_with(
            {"body": "⚠️ CodeGuardian Error: API rate limit exceeded"}
        )


class TestGitLabUrl:
    """Tests for GitLab URL configuration."""

    def test_gitlab_url_defaults_to_gitlab_com(self):
        """Default gitlab_url is https://gitlab.com."""
        with patch("src.gitlab_client.gitlab.Gitlab") as mock_gl_cls:
            mock_gl = MagicMock()
            mock_gl.projects.get.return_value = MagicMock()
            mock_gl.projects.get.return_value.mergerequests.get.return_value = (
                MagicMock()
            )
            mock_gl_cls.return_value = mock_gl

            GitLabClient(token="test-token", project_id=1, mr_iid=1)

            mock_gl_cls.assert_called_once_with(
                "https://gitlab.com", private_token="test-token"
            )

    def test_gitlab_url_custom_self_hosted(self):
        """Custom gitlab_url is passed to Gitlab client."""
        with patch("src.gitlab_client.gitlab.Gitlab") as mock_gl_cls:
            mock_gl = MagicMock()
            mock_gl.projects.get.return_value = MagicMock()
            mock_gl.projects.get.return_value.mergerequests.get.return_value = (
                MagicMock()
            )
            mock_gl_cls.return_value = mock_gl

            GitLabClient(
                token="test-token",
                project_id=1,
                mr_iid=1,
                gitlab_url="https://gitlab.mycompany.com",
            )

            mock_gl_cls.assert_called_once_with(
                "https://gitlab.mycompany.com", private_token="test-token"
            )


class TestGetFileContentSuccess:
    """get_file_content returns decoded content when file exists."""

    def test_returns_decoded_content(self, client, mock_project):
        mock_file_obj = MagicMock()
        mock_file_obj.decode.return_value = b"# My Project"
        mock_project.files.get.return_value = mock_file_obj

        result = client.get_file_content("AGENTS.md")

        assert result == "# My Project"
        mock_project.files.get.assert_called_once_with(
            file_path="AGENTS.md", ref="main"
        )


class TestGetFileContentNotFound:
    """get_file_content returns None when file doesn't exist."""

    def test_returns_none_on_not_found(self, client, mock_project):
        mock_project.files.get.side_effect = GitlabGetError("404 File Not Found")

        result = client.get_file_content("AGENTS.md")

        assert result is None


class TestGetFileContentError:
    """get_file_content returns None on generic exception."""

    def test_returns_none_on_generic_error(self, client, mock_project):
        mock_project.files.get.side_effect = Exception("Connection error")

        result = client.get_file_content("AGENTS.md")

        assert result is None
