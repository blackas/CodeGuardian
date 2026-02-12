"""GitLab client implementing CodeReviewPlatform protocol."""

import logging

import gitlab
from gitlab.exceptions import GitlabCreateError, GitlabGetError

from src.platform_protocol import PlatformContext, PlatformFile

logger = logging.getLogger(__name__)


class GitLabClient:
    """GitLab Merge Request client implementing CodeReviewPlatform protocol.

    Uses python-gitlab to interact with GitLab API for code review operations.
    """

    def __init__(
        self,
        token: str,
        project_id: int,
        mr_iid: int,
        gitlab_url: str = "https://gitlab.com",
    ) -> None:
        """Initialize GitLab client with project and MR references.

        Args:
            token: GitLab Project Access Token (private_token).
            project_id: GitLab project ID.
            mr_iid: Merge request internal ID.
            gitlab_url: GitLab instance URL. Defaults to https://gitlab.com.
        """
        self._gitlab = gitlab.Gitlab(gitlab_url, private_token=token)
        self._project = self._gitlab.projects.get(project_id)
        self._merge_request = self._project.mergerequests.get(mr_iid)
        self._project_id = project_id

    def get_context(self) -> PlatformContext:
        """Get MR context information.

        Returns:
            PlatformContext with MR metadata.
        """
        merge_request = self._merge_request
        return PlatformContext(
            number=merge_request.iid,
            title=merge_request.title,
            description=merge_request.description or "",
            head_sha=merge_request.sha,
            repo_identifier=str(self._project_id),
        )

    def get_files(self) -> list[PlatformFile]:
        """Get list of files changed in the MR.

        Calls mr.changes() and converts each change to a PlatformFile,
        counting '+' and '-' lines for additions/deletions.

        Returns:
            List of PlatformFile objects.
        """
        changes = self._merge_request.changes()["changes"]
        files = []
        for change in changes:
            diff_text = change.get("diff", "")
            additions = 0
            deletions = 0
            for line in diff_text.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deletions += 1
            files.append(
                PlatformFile(
                    filename=change["new_path"],
                    patch=diff_text if diff_text else None,
                    additions=additions,
                    deletions=deletions,
                )
            )
        return files

    def is_fork(self) -> bool:
        """Check if MR is from a fork.

        Returns:
            Always False for GitLab v1 (fork detection not needed).
        """
        return False

    def post_review_comments(
        self, comments: list[dict[str, str | int]], summary: str
    ) -> None:
        """Post review comments as MR discussions and summary as a note.

        For each comment, creates an inline discussion using diff_refs.
        If a GitlabCreateError occurs (e.g., line outside diff), the
        comment is skipped with a warning log.

        Args:
            comments: List of comment dicts with 'path', 'body', 'line' keys.
            summary: Summary comment text posted as MR note.
        """
        merge_request = self._merge_request
        diff_refs = merge_request.diff_refs

        for comment in comments:
            try:
                merge_request.discussions.create(
                    {
                        "body": comment["body"],
                        "position": {
                            "base_sha": diff_refs["base_sha"],
                            "start_sha": diff_refs["start_sha"],
                            "head_sha": diff_refs["head_sha"],
                            "position_type": "text",
                            "new_path": comment["path"],
                            "new_line": comment["line"],
                        },
                    }
                )
            except GitlabCreateError as error:
                logger.warning(
                    "Failed to create inline comment on %s:%s - %s",
                    comment["path"],
                    comment["line"],
                    error,
                )

        merge_request.notes.create({"body": summary})

    def post_error_comment(self, error_message: str) -> None:
        """Post an error comment to the MR.

        Args:
            error_message: Error message text.
        """
        self._merge_request.notes.create(
            {"body": f"⚠️ CodeGuardian Error: {error_message}"}
        )

    def get_file_content(self, file_path: str) -> str | None:
        """Get the content of a file from the base branch.

        Args:
            file_path: Path to the file relative to repo root.

        Returns:
            File content as string, or None if file not found.
        """
        try:
            file_obj = self._project.files.get(
                file_path=file_path, ref=self._merge_request.target_branch
            )
            return file_obj.decode().decode("utf-8")
        except GitlabGetError:
            logger.warning(
                "File not found: %s on branch %s",
                file_path,
                self._merge_request.target_branch,
            )
            return None
        except Exception:
            logger.warning("Error reading file: %s", file_path)
            return None
