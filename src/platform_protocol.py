"""Platform-agnostic protocol for code review integrations."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class PlatformFile:
    """Represents a file in a code review."""

    filename: str
    """File path relative to repo root."""

    patch: str | None
    """Unified diff patch. None for binary files."""

    additions: int
    """Number of added lines."""

    deletions: int
    """Number of deleted lines."""


@dataclass
class PlatformContext:
    """Context information for a code review (PR/MR)."""

    number: int
    """PR/MR number."""

    title: str
    """PR/MR title."""

    description: str
    """PR/MR body/description."""

    head_sha: str
    """Head commit SHA."""

    repo_identifier: str
    """GitHub: 'owner/repo', GitLab: project ID."""


@runtime_checkable
class CodeReviewPlatform(Protocol):
    """Protocol for platform-agnostic code review integrations.

    Implementations should support GitHub, GitLab, or other platforms
    by providing these methods.
    """

    def get_context(self) -> PlatformContext:
        """Get the PR/MR context information.

        Returns:
            PlatformContext with PR/MR metadata.
        """
        ...

    def get_files(self) -> list[PlatformFile]:
        """Get the list of files changed in the PR/MR.

        Returns:
            List of PlatformFile objects.
        """
        ...

    def is_fork(self) -> bool:
        """Check if the PR/MR is from a fork.

        Returns:
            True if from a fork, False otherwise.
        """
        ...

    def post_review_comments(
        self, comments: list[dict[str, str | int]], summary: str
    ) -> None:
        """Post review comments to the PR/MR.

        Args:
            comments: List of comment dicts with keys:
                - path: str (file path)
                - body: str (comment text)
                - line: int (line number)
            summary: Summary comment text.
        """
        ...

    def post_error_comment(self, error_message: str) -> None:
        """Post an error comment to the PR/MR.

        Args:
            error_message: Error message text.
        """
        ...

    def get_file_content(self, file_path: str) -> str | None:
        """Get the content of a file from the base branch.

        Args:
            file_path: Path to the file relative to repo root.

        Returns:
            File content as string, or None if file not found.
        """
        ...
