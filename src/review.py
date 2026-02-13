"""Main orchestrator for CodeGuardian with dual-platform auto-detection."""

import json
import os
import sys

from src.ai_reviewer import AIReviewer, ReviewComment
from src.diff_parser import filter_reviewable_files, get_valid_comment_lines
from src.github_client import GitHubClient
from src.gitlab_client import GitLabClient
from src.platform_protocol import CodeReviewPlatform


def load_event_data(event_path: str) -> dict:
    """Load GitHub webhook event JSON data from file.

    Args:
        event_path: Path to the GitHub event JSON file.

    Returns:
        Parsed event data dictionary.
    """
    with open(event_path, "r") as file:
        return json.load(file)


def _fetch_project_context(platform: CodeReviewPlatform) -> str:
    """Fetch AGENTS.md from repo base branch for project context.

    Args:
        platform: Platform client with get_file_content method.

    Returns:
        AGENTS.md content, or empty string if not found.
    """
    content = platform.get_file_content("AGENTS.md")
    if content and content.strip():
        return content
    return ""


def _build_event_data_from_pr(
    token: str, repo_name: str, pr_number: int
) -> dict[str, object]:
    """Build synthetic event data by fetching PR info from GitHub API.

    Used for manual triggers (workflow_dispatch, issue_comment) where
    GITHUB_EVENT_PATH doesn't contain pull_request data.

    Args:
        token: GitHub API token.
        repo_name: Repository full name (owner/repo).
        pr_number: Pull request number.

    Returns:
        Synthetic event data dict compatible with GitHubClient.
    """
    from github import Github

    g = Github(token)
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    return {
        "repository": {"full_name": repo_name},
        "pull_request": {
            "number": pr.number,
            "title": pr.title,
            "body": pr.body or "",
            "head": {
                "sha": pr.head.sha,
                "repo": {
                    "full_name": (pr.head.repo.full_name if pr.head.repo else repo_name)
                },
            },
            "base": {
                "ref": pr.base.ref,
                "repo": {
                    "full_name": (pr.base.repo.full_name if pr.base.repo else repo_name)
                },
            },
        },
    }


def create_platform() -> CodeReviewPlatform:
    """Auto-detect CI platform and create the appropriate client.

    Checks environment variables to determine if running on GitHub Actions
    or GitLab CI, then creates and returns the corresponding client.
    Supports manual triggers via PR_NUMBER env var.

    Priority order:
    1. PR_NUMBER env var (manual trigger via workflow_dispatch or /review comment)
    2. GITHUB_EVENT_PATH (automatic GitHub Actions trigger)
    3. CI_MERGE_REQUEST_IID (automatic GitLab CI trigger)

    Returns:
        Platform client implementing CodeReviewPlatform protocol.

    Raises:
        SystemExit: If no supported platform is detected.
    """
    # Manual trigger: PR_NUMBER takes priority over event data
    pr_number_str = os.environ.get("PR_NUMBER", "").strip()
    if pr_number_str and pr_number_str != "0":
        token = os.environ["GITHUB_TOKEN"]
        repo_name = os.environ.get("REPO_NAME") or os.environ.get(
            "GITHUB_REPOSITORY", ""
        )
        if not repo_name:
            print("ERROR: REPO_NAME or GITHUB_REPOSITORY must be set with PR_NUMBER.")
            sys.exit(1)
        try:
            event_data = _build_event_data_from_pr(token, repo_name, int(pr_number_str))
        except Exception as e:
            print(f"ERROR: Failed to fetch PR #{pr_number_str} from {repo_name}: {e}")
            sys.exit(1)
        return GitHubClient(token=token, repo_name=repo_name, event_data=event_data)

    # Auto-detect from CI environment
    if os.environ.get("GITHUB_EVENT_PATH"):
        event_data = load_event_data(os.environ["GITHUB_EVENT_PATH"])
        return GitHubClient(
            token=os.environ["GITHUB_TOKEN"],
            repo_name=event_data["repository"]["full_name"],
            event_data=event_data,
        )
    elif os.environ.get("CI_MERGE_REQUEST_IID"):
        return GitLabClient(
            token=os.environ["GITLAB_TOKEN"],
            project_id=int(os.environ["CI_PROJECT_ID"]),
            mr_iid=int(os.environ["CI_MERGE_REQUEST_IID"]),
            gitlab_url=os.environ.get("CI_SERVER_URL", "https://gitlab.com"),
        )
    else:
        print(
            "ERROR: Could not detect platform. Set GITHUB_EVENT_PATH or CI_MERGE_REQUEST_IID."
        )
        sys.exit(1)


def validate_comment_lines(
    comments: list[ReviewComment], file_patches: dict[str, str]
) -> list[ReviewComment]:
    """Filter review comments to only those on valid diff lines.

    Checks each comment's line_number against the valid lines from the
    file's patch. Comments on lines not in the diff are discarded.

    Args:
        comments: List of ReviewComment from AI reviewer.
        file_patches: Mapping of file_path to patch string.

    Returns:
        Filtered list of ReviewComment with valid line numbers only.
    """
    valid_comments: list[ReviewComment] = []
    for comment in comments:
        patch = file_patches.get(comment.file_path)
        if patch is None:
            print(f"WARNING: No patch for {comment.file_path}, skipping comment")
            continue
        valid_lines = get_valid_comment_lines(patch)
        if comment.line_number in valid_lines:
            valid_comments.append(comment)
        else:
            print(
                f"WARNING: Discarding comment on {comment.file_path}:{comment.line_number} "
                f"(not in diff valid lines)"
            )
    return valid_comments


def format_comment_body(comment: ReviewComment) -> str:
    """Format a review comment into a readable string.

    Args:
        comment: ReviewComment to format.

    Returns:
        Formatted string: **[severity] [category]**: comment
    """
    return f"**[{comment.severity}] [{comment.category}]**: {comment.comment}"


def build_summary(comments: list[ReviewComment]) -> str:
    """Build a summary string with severity breakdown.

    Args:
        comments: List of ReviewComment to summarize.

    Returns:
        Summary string like "CodeGuardian Review: Found 3 issues (2 errors, 1 warning, 0 info)"
    """
    error_count = sum(1 for c in comments if c.severity == "error")
    warning_count = sum(1 for c in comments if c.severity == "warning")
    info_count = sum(1 for c in comments if c.severity == "info")
    total = len(comments)

    return (
        f"CodeGuardian Review: Found {total} issues "
        f"({error_count} errors, {warning_count} warnings, {info_count} info)"
    )


def main() -> None:
    """Run the CodeGuardian review pipeline.

    Pipeline steps:
    1. Auto-detect platform and create client
    2. Get PR/MR context (title, description, head_sha)
    3. Check if PR is from a fork (exit early if so)
    4. Get changed files and filter to reviewable ones
    5. Run AI review on reviewable files
    6. Validate comment line numbers against diff
    7. Post review comments and summary to platform
    """
    platform = create_platform()
    context = platform.get_context()

    # Fetch project context from AGENTS.md on base branch
    project_context = _fetch_project_context(platform)

    # Fork check: skip review to avoid leaking secrets
    if platform.is_fork():
        print("WARNING: PR is from a fork. Skipping review to protect secrets.")
        sys.exit(0)

    # Get and filter files
    raw_files = platform.get_files()
    file_dicts = [
        {
            "filename": f.filename,
            "patch": f.patch,
            "additions": f.additions,
            "deletions": f.deletions,
        }
        for f in raw_files
    ]
    reviewable = filter_reviewable_files(file_dicts)

    if not reviewable:
        platform.post_error_comment("No reviewable files found in this PR/MR.")
        sys.exit(0)

    # Initialize AI reviewer
    api_key = os.environ.get("OPENAI_API_KEY", "")
    reviewer = AIReviewer(api_key=api_key, project_context=project_context)

    try:
        # Prepare files for review
        review_files = [
            {"file_path": f["filename"], "patch": f["patch"]} for f in reviewable
        ]
        ai_comments = reviewer.review_files(
            files=review_files,
            pr_title=context.title,
            pr_description=context.description,
        )

        # Build file_patches map for line validation
        file_patches = {f["filename"]: f["patch"] for f in reviewable}

        # Validate comment lines
        valid_comments = validate_comment_lines(ai_comments, file_patches)

        # Format comments for platform
        platform_comments = [
            {
                "path": comment.file_path,
                "body": format_comment_body(comment),
                "line": comment.line_number,
            }
            for comment in valid_comments
        ]

        # Build summary and post
        summary = build_summary(valid_comments)
        platform.post_review_comments(platform_comments, summary)

    except Exception as error:
        platform.post_error_comment(f"CodeGuardian encountered an error: {error}")


if __name__ == "__main__":
    main()
