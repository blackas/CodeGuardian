"""GitHub webhook server for self-hosted CodeGuardian reviews."""

import hashlib
import hmac
import logging
import os
import threading

from fastapi import FastAPI, Header, HTTPException, Request

from src.ai_reviewer import ReviewComment
from src.codex_reviewer import CodexReviewer
from src.diff_parser import filter_reviewable_files
from src.github_client import GitHubClient
from src.review import build_summary, format_comment_body, validate_comment_lines

logger = logging.getLogger(__name__)

app = FastAPI(title="CodeGuardian Webhook Server")


def _verify_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    if not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def run_review(event_data: dict) -> None:
    """Run the CodeGuardian review pipeline for a PR event."""
    try:
        token = os.environ["GITHUB_TOKEN"]
        repo_name = event_data["repository"]["full_name"]

        platform = GitHubClient(
            token=token, repo_name=repo_name, event_data=event_data
        )
        context = platform.get_context()

        agents_content = platform.get_file_content("AGENTS.md")
        project_context = agents_content if agents_content and agents_content.strip() else ""

        if platform.is_fork():
            logger.warning("PR is from a fork. Skipping review.")
            return

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
            platform.post_error_comment("No reviewable files found in this PR.")
            return

        reviewer = CodexReviewer(project_context=project_context)

        review_files = [
            {"file_path": f["filename"], "patch": f["patch"]} for f in reviewable
        ]
        ai_comments = reviewer.review_files(
            files=review_files,
            pr_title=context.title,
            pr_description=context.description,
        )

        file_patches = {f["filename"]: f["patch"] for f in reviewable}
        valid_comments = validate_comment_lines(ai_comments, file_patches)

        platform_comments = [
            {
                "path": c.file_path,
                "body": format_comment_body(c),
                "line": c.line_number,
            }
            for c in valid_comments
        ]

        summary = build_summary(valid_comments)
        platform.post_review_comments(platform_comments, summary)

    except Exception as e:
        logger.exception("Review failed for PR")
        try:
            token = os.environ.get("GITHUB_TOKEN", "")
            repo_name = event_data.get("repository", {}).get("full_name", "")
            if token and repo_name:
                platform = GitHubClient(
                    token=token, repo_name=repo_name, event_data=event_data
                )
                platform.post_error_comment(f"CodeGuardian error: {e}")
        except Exception:
            logger.exception("Failed to post error comment")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
):
    secret = os.environ.get("WEBHOOK_SECRET", "")
    payload = await request.body()

    if not _verify_signature(payload, x_hub_signature_256, secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    if x_github_event != "pull_request":
        return {"status": "ignored"}

    event_data = await request.json()
    action = event_data.get("action", "")

    if action not in ("opened", "synchronize"):
        return {"status": "ignored", "action": action}

    thread = threading.Thread(target=run_review, args=(event_data,), daemon=True)
    thread.start()

    pr_number = event_data.get("pull_request", {}).get("number")
    return {"status": "processing", "pr_number": pr_number}
