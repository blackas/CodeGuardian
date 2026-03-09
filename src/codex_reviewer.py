"""Code reviewer using Codex CLI with structured output."""

import json
import logging
import subprocess
from pathlib import Path

from src.ai_reviewer import ReviewComment, ReviewResponse

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "review_schema.json"


class CodexReviewer:
    """Code reviewer powered by Codex CLI (ChatGPT Plus OAuth).

    Uses `codex exec --output-schema` for structured review output.
    Requires Codex CLI installed and authenticated (`codex login`).
    """

    def __init__(self, project_context: str = "") -> None:
        self._project_context = project_context
        self._rate_limit_failure_count = 0

    def review_diff(
        self,
        file_path: str,
        patch: str,
        pr_title: str,
        pr_description: str,
    ) -> ReviewResponse:
        prompt = self._build_prompt(file_path, patch, pr_title, pr_description)
        return self._call_codex(prompt)

    def review_files(
        self,
        files: list[dict[str, str]],
        pr_title: str,
        pr_description: str,
    ) -> list[ReviewComment]:
        all_comments: list[ReviewComment] = []
        for file_info in files:
            response = self.review_diff(
                file_path=file_info["file_path"],
                patch=file_info["patch"],
                pr_title=pr_title,
                pr_description=pr_description,
            )
            all_comments.extend(response.comments)
        return all_comments

    def _build_prompt(
        self,
        file_path: str,
        patch: str,
        pr_title: str,
        pr_description: str,
    ) -> str:
        context_section = ""
        if self._project_context:
            context_section = (
                f"Project context:\n{self._project_context}\n\n"
            )

        return (
            f"You are a senior code reviewer. Review the following code diff and return structured JSON feedback.\n\n"
            f"{context_section}"
            f"Focus on: logic errors, security vulnerabilities, performance issues, readability.\n\n"
            f"File: {file_path}\n"
            f"PR Title: {pr_title}\n"
            f"PR Description: {pr_description}\n\n"
            f"Diff:\n```\n{patch}\n```\n\n"
            f"Return JSON with 'comments' array and 'summary' string."
        )

    def _call_codex(self, prompt: str) -> ReviewResponse:
        try:
            result = subprocess.run(
                [
                    "codex", "exec", prompt,
                    "--output-schema", str(SCHEMA_PATH),
                    "-o", "/dev/stdout",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                logger.error("Codex exec failed: %s", result.stderr)
                return ReviewResponse(
                    comments=[],
                    summary=f"Error: Codex exec failed: {result.stderr[:200]}",
                )

            parsed = json.loads(result.stdout)
            return ReviewResponse.model_validate(parsed)

        except subprocess.TimeoutExpired:
            logger.error("Codex exec timed out")
            return ReviewResponse(
                comments=[],
                summary="Error: Codex exec timed out after 120 seconds.",
            )
        except (json.JSONDecodeError, Exception) as e:
            logger.error("Failed to parse Codex output: %s", e)
            return ReviewResponse(
                comments=[],
                summary=f"Error: Failed to parse Codex output: {e}",
            )

    @property
    def rate_limit_failure_count(self) -> int:
        return self._rate_limit_failure_count
