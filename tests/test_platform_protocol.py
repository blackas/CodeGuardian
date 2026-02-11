"""Tests for platform_protocol module."""

import pytest
from src.platform_protocol import (
    PlatformFile,
    PlatformContext,
    CodeReviewPlatform,
)


class TestPlatformFileDataclass:
    """Test PlatformFile dataclass creation and field access."""

    def test_platform_file_dataclass(self):
        """Create and access all fields of PlatformFile."""
        file = PlatformFile(
            filename="src/main.py",
            patch="@@ -1,3 +1,4 @@\n-old\n+new",
            additions=1,
            deletions=1,
        )
        assert file.filename == "src/main.py"
        assert file.patch == "@@ -1,3 +1,4 @@\n-old\n+new"
        assert file.additions == 1
        assert file.deletions == 1

    def test_platform_file_none_patch(self):
        """Binary file with patch=None."""
        file = PlatformFile(
            filename="image.png",
            patch=None,
            additions=0,
            deletions=0,
        )
        assert file.filename == "image.png"
        assert file.patch is None
        assert file.additions == 0
        assert file.deletions == 0


class TestPlatformContextDataclass:
    """Test PlatformContext dataclass creation and field access."""

    def test_platform_context_dataclass(self):
        """Create and access all fields of PlatformContext."""
        context = PlatformContext(
            number=42,
            title="Fix critical bug",
            description="This PR fixes issue #123",
            head_sha="abc123def456",
            repo_identifier="owner/repo",
        )
        assert context.number == 42
        assert context.title == "Fix critical bug"
        assert context.description == "This PR fixes issue #123"
        assert context.head_sha == "abc123def456"
        assert context.repo_identifier == "owner/repo"


class TestProtocolStructuralSubtyping:
    """Test Protocol structural subtyping with isinstance."""

    def test_protocol_structural_subtyping(self):
        """Dummy class implements Protocol → isinstance passes."""

        class DummyPlatform:
            def get_context(self) -> PlatformContext:
                return PlatformContext(
                    number=1,
                    title="Test",
                    description="",
                    head_sha="abc",
                    repo_identifier="test/repo",
                )

            def get_files(self) -> list[PlatformFile]:
                return []

            def is_fork(self) -> bool:
                return False

            def post_review_comments(self, comments: list[dict], summary: str) -> None:
                pass

            def post_error_comment(self, error_message: str) -> None:
                pass

        dummy = DummyPlatform()
        assert isinstance(dummy, CodeReviewPlatform)

    def test_protocol_rejects_incomplete(self):
        """Class missing method → isinstance fails."""

        class IncompletePlatform:
            def get_context(self) -> PlatformContext:
                return PlatformContext(
                    number=1,
                    title="Test",
                    description="",
                    head_sha="abc",
                    repo_identifier="test/repo",
                )

            def get_files(self) -> list[PlatformFile]:
                return []

            # Missing: is_fork, post_review_comments, post_error_comment

        incomplete = IncompletePlatform()
        assert not isinstance(incomplete, CodeReviewPlatform)
