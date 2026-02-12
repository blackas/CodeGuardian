"""AI-powered code reviewer using OpenAI GPT-4o-mini with structured output."""

import json
import logging
import os
import re
import time
from typing import Literal

from openai import AuthenticationError, BadRequestError, OpenAI, RateLimitError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MAX_INPUT_LENGTH = 500
MAX_RETRIES = 3
MODEL_NAME = "gpt-4o-mini"
TEMPERATURE = 0.2


class ReviewComment(BaseModel):
    """A single review comment on a specific line of code."""

    file_path: str
    line_number: int
    severity: Literal["error", "warning", "info"]
    category: Literal["bug", "security", "performance", "readability"]
    comment: str


class ReviewResponse(BaseModel):
    """Structured response from the AI reviewer."""

    comments: list[ReviewComment]
    summary: str


class AIReviewer:
    """Code reviewer powered by OpenAI GPT-4o-mini with structured output.

    Uses structured JSON output to ensure consistent, parseable review comments.
    Supports dynamic project context to tailor reviews to specific codebases.
    """

    def __init__(self, api_key: str, project_context: str = "") -> None:
        """Initialize the AI reviewer.

        Args:
            api_key: OpenAI API key. Use "mock" for mock mode.
            project_context: Optional project context (e.g., AGENTS.md content) to inform reviews.
        """
        self._api_key = api_key
        self._project_context = project_context
        self._is_mock = api_key == "mock" or not api_key
        if not self._is_mock:
            self._client: OpenAI = OpenAI(api_key=api_key)
        else:
            self._client: OpenAI = None  # type: ignore[assignment]

    def review_diff(
        self,
        file_path: str,
        patch: str,
        pr_title: str,
        pr_description: str,
    ) -> ReviewResponse:
        """Review a single file diff and return structured comments.

        Args:
            file_path: Path to the file being reviewed.
            patch: Unified diff patch content.
            pr_title: Pull request title for context.
            pr_description: Pull request description for context.

        Returns:
            ReviewResponse with comments and summary.

        Raises:
            AuthenticationError: If the API key is invalid.
        """
        if self._is_mock:
            return self._mock_response(file_path)

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            file_path, patch, pr_title, pr_description
        )

        return self._call_openai(system_prompt, user_prompt)

    def review_files(
        self,
        files: list[dict[str, str]],
        pr_title: str,
        pr_description: str,
    ) -> list[ReviewComment]:
        """Review multiple files and aggregate all comments.

        Args:
            files: List of dicts with 'file_path' and 'patch' keys.
            pr_title: Pull request title for context.
            pr_description: Pull request description for context.

        Returns:
            Aggregated list of ReviewComment from all files.

        Raises:
            AuthenticationError: If the API key is invalid.
        """
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

    def _build_system_prompt(self) -> str:
        """Build the system prompt, optionally with project context.

        Returns:
            System prompt string, either context-aware or generic.
        """
        if self._project_context:
            return (
                "You are a senior code reviewer. The following describes the project you are reviewing:\n\n"
                f"{self._project_context}\n\n"
                "Based on this project context, review the provided code diff and return structured JSON feedback. "
                "For each issue found, provide the file path, line number, severity (error/warning/info), "
                "category (bug/security/performance/readability), and a clear explanation of the issue and suggested fix."
            )
        else:
            return (
                "You are a senior code reviewer. Review the provided code diff and return structured JSON feedback.\n\n"
                "Focus on:\n"
                "1. Logic errors and potential bugs\n"
                "2. Security vulnerabilities\n"
                "3. Performance issues\n"
                "4. Code readability and maintainability\n\n"
                "For each issue found, provide the file path, line number, severity (error/warning/info), "
                "category (bug/security/performance/readability), and a clear explanation of the issue and suggested fix."
            )

    def _build_user_prompt(
        self,
        file_path: str,
        patch: str,
        pr_title: str,
        pr_description: str,
    ) -> str:
        """Build the user prompt for a single file review.

        Args:
            file_path: Path to the file being reviewed.
            patch: Unified diff patch content.
            pr_title: Pull request title.
            pr_description: Pull request description.

        Returns:
            Formatted user prompt string.
        """
        sanitized_title = self._sanitize_input(pr_title)
        sanitized_description = self._sanitize_input(pr_description)
        sanitized_patch = self._sanitize_input(patch)

        return (
            f"Review the following code diff:\n\n"
            f"File: {file_path}\n"
            f"PR Title: {sanitized_title}\n"
            f"PR Description: {sanitized_description}\n\n"
            f"Diff:\n```\n{sanitized_patch}\n```\n\n"
            f"Provide your review as structured JSON."
        )

    def _sanitize_input(self, text: str) -> str:
        """Strip markdown formatting and truncate to max length.

        Args:
            text: Raw input text to sanitize.

        Returns:
            Sanitized text with markdown removed and length capped.
        """
        if not text:
            return ""

        # Strip markdown images ![alt](url) -> alt (before links)
        sanitized = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
        # Strip markdown bold/italic
        sanitized = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", sanitized)
        # Strip markdown links [text](url) -> text
        sanitized = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", sanitized)
        # Strip markdown headers
        sanitized = re.sub(r"^#{1,6}\s+", "", sanitized, flags=re.MULTILINE)
        # Strip markdown code backticks
        sanitized = re.sub(r"`{1,3}", "", sanitized)

        # Truncate to max length
        if len(sanitized) > MAX_INPUT_LENGTH:
            sanitized = sanitized[:MAX_INPUT_LENGTH]

        return sanitized

    def _call_openai(self, system_prompt: str, user_prompt: str) -> ReviewResponse:
        """Call OpenAI API with structured output and error handling.

        Args:
            system_prompt: System prompt for the model.
            user_prompt: User prompt with the diff to review.

        Returns:
            Parsed ReviewResponse from the model.

        Raises:
            AuthenticationError: If the API key is invalid.
        """
        last_exception: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=MODEL_NAME,
                    temperature=TEMPERATURE,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "code_review",
                            "strict": True,
                            "schema": ReviewResponse.model_json_schema(),
                        },
                    },
                )

                choice = response.choices[0]

                # Safety refusal
                if choice.message.refusal:
                    logger.warning("Model refused request: %s", choice.message.refusal)
                    return ReviewResponse(comments=[], summary="")

                # Token truncation
                if choice.finish_reason == "length":
                    logger.warning("Response truncated due to token limit")
                    return ReviewResponse(
                        comments=[],
                        summary="Error: Response truncated due to token limit.",
                    )

                raw_content = choice.message.content or ""
                parsed = json.loads(raw_content)
                return ReviewResponse.model_validate(parsed)

            except AuthenticationError:
                raise

            except BadRequestError as error:
                logger.warning("Content filter triggered: %s", error)
                return ReviewResponse(
                    comments=[],
                    summary="Error: Content was filtered by the API.",
                )

            except RateLimitError as error:
                last_exception = error
                if attempt < MAX_RETRIES - 1:
                    wait_time = 2 ** (attempt + 1)
                    logger.info(
                        "Rate limited. Retrying in %d seconds (attempt %d/%d)",
                        wait_time,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(wait_time)

        logger.error("Max retries exceeded for rate limit errors")
        return ReviewResponse(
            comments=[],
            summary=f"Error: Rate limit exceeded after {MAX_RETRIES} retries.",
        )

    def _mock_response(self, file_path: str) -> ReviewResponse:
        """Return a canned mock response for testing without API access.

        Args:
            file_path: Path to the file being reviewed.

        Returns:
            Static ReviewResponse with sample comments.
        """
        return ReviewResponse(
            comments=[
                ReviewComment(
                    file_path=file_path,
                    line_number=1,
                    severity="info",
                    category="readability",
                    comment="Mock review comment for testing.",
                )
            ],
            summary="Mock review completed.",
        )
