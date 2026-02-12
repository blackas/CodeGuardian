"""GitHub implementation of the CodeReviewPlatform protocol."""

from __future__ import annotations

import logging
from typing import Any

from github import Github, GithubException
from github.GithubException import UnknownObjectException

from src.platform_protocol import PlatformContext, PlatformFile

logger = logging.getLogger(__name__)

REVIEW_COMMENT_CHUNK_SIZE = 30


class GitHubClient:
    """GitHub code review client implementing CodeReviewPlatform protocol.

    Uses PyGithub to interact with the GitHub API for PR reviews.
    """

    def __init__(self, token: str, repo_name: str, event_data: dict[str, Any]) -> None:
        """Initialize GitHub client.

        Args:
            token: GitHub API token.
            repo_name: Repository full name (owner/repo).
            event_data: GitHub webhook event payload.
        """
        self._github = Github(token)
        self._repo = self._github.get_repo(repo_name)
        self._event_data = event_data
        self._pr_number: int = event_data["pull_request"]["number"]
        self._pr = self._repo.get_pull(self._pr_number)

    def get_context(self) -> PlatformContext:
        """Get the PR context information from event data.

        Returns:
            PlatformContext with PR metadata.
        """
        pull_request = self._event_data["pull_request"]
        return PlatformContext(
            number=pull_request["number"],
            title=pull_request["title"],
            description=pull_request.get("body", "") or "",
            head_sha=pull_request["head"]["sha"],
            repo_identifier=self._event_data["repository"]["full_name"],
        )

    def get_files(self) -> list[PlatformFile]:
        """Get the list of files changed in the PR.

        Returns:
            List of PlatformFile objects from the PR.
        """
        return [
            PlatformFile(
                filename=file.filename,
                patch=file.patch,
                additions=file.additions,
                deletions=file.deletions,
            )
            for file in self._pr.get_files()
        ]

    def is_fork(self) -> bool:
        """Check if the PR is from a fork.

        Returns:
            True if the head repo differs from the base repo.
        """
        head_repo = self._event_data["pull_request"]["head"]["repo"]["full_name"]
        base_repo = self._event_data["pull_request"]["base"]["repo"]["full_name"]
        return head_repo != base_repo

    def post_review_comments(
        self, comments: list[dict[str, str | int]], summary: str
    ) -> None:
        """Post review comments to the PR.

        Posts comments in batches of 30 using create_review. Falls back to
        individual create_review_comment calls on 422 errors.

        Args:
            comments: List of comment dicts with keys: path, body, line.
            summary: Summary comment text.
        """
        if not comments:
            return

        commits = self._pr.get_commits()
        last_commit = list(commits)[-1]

        github_comments = [
            {
                "path": comment["path"],
                "body": comment["body"],
                "line": comment["line"],
                "side": "RIGHT",
            }
            for comment in comments
        ]

        chunks = self._chunk_comments(github_comments, REVIEW_COMMENT_CHUNK_SIZE)

        for chunk in chunks:
            try:
                self._pr.create_review(
                    commit=last_commit,
                    comments=chunk,
                    event="COMMENT",
                    body=summary,
                )
            except GithubException as error:
                if error.status == 422:
                    logger.warning(
                        "Batch review failed with 422, falling back to individual comments"
                    )
                    self._post_individual_comments(chunk, last_commit)
                else:
                    raise

    def post_error_comment(self, error_message: str) -> None:
        """Post an error comment to the PR.

        Args:
            error_message: Error message text.
        """
        self._pr.create_issue_comment(body=error_message)

    def get_file_content(self, file_path: str) -> str | None:
        """Get the content of a file from the base branch.

        Args:
            file_path: Path to the file relative to repo root.

        Returns:
            File content as string, or None if file not found.
        """
        try:
            base_ref = self._event_data["pull_request"]["base"]["ref"]
            content_file = self._repo.get_contents(file_path, ref=base_ref)
            return content_file.decoded_content.decode("utf-8")
        except UnknownObjectException:
            logger.warning("File not found: %s on branch %s", file_path, base_ref)
            return None

    def _chunk_comments(
        self,
        comments: list[dict[str, Any]],
        chunk_size: int = REVIEW_COMMENT_CHUNK_SIZE,
    ) -> list[list[dict[str, Any]]]:
        """Split comments into chunks of specified size.

        Args:
            comments: List of comment dicts.
            chunk_size: Maximum comments per chunk.

        Returns:
            List of comment chunks.
        """
        return [
            comments[i : i + chunk_size] for i in range(0, len(comments), chunk_size)
        ]

    def _post_individual_comments(
        self, comments: list[dict[str, Any]], commit: Any
    ) -> None:
        """Post comments individually as fallback.

        Args:
            comments: List of GitHub-formatted comment dicts.
            commit: The commit object to attach comments to.
        """
        for comment in comments:
            try:
                self._pr.create_review_comment(
                    body=comment["body"],
                    commit=commit,
                    path=comment["path"],
                    line=comment["line"],
                    side="RIGHT",
                )
            except GithubException as error:
                logger.warning(
                    "Skipping comment on %s line %s: %s",
                    comment["path"],
                    comment["line"],
                    error,
                )
