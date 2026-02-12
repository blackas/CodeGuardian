"""Tests for AI reviewer module with OpenAI GPT-4o-mini integration."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from openai import AuthenticationError, BadRequestError, RateLimitError
from pydantic import BaseModel

from src.ai_reviewer import AIReviewer, ReviewComment, ReviewResponse


def _make_openai_response(
    content: dict | str,
    finish_reason: str = "stop",
    refusal: str | None = None,
) -> MagicMock:
    """Build a mock OpenAI ChatCompletion response.

    Args:
        content: Response content dict (will be JSON-serialized) or raw string.
        finish_reason: The finish_reason field value.
        refusal: Optional refusal message.

    Returns:
        MagicMock mimicking openai ChatCompletion response structure.
    """
    if isinstance(content, dict):
        raw = json.dumps(content)
    else:
        raw = content

    message = SimpleNamespace(content=raw, refusal=refusal)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


SAMPLE_REVIEW = {
    "comments": [
        {
            "file_path": "src/main.py",
            "line_number": 10,
            "severity": "warning",
            "category": "bug",
            "comment": "Potential float comparison issue.",
        }
    ],
    "summary": "Found 1 issue.",
}


class TestReviewDiffReturnsStructuredResponse:
    """Test that review_diff returns a properly structured ReviewResponse."""

    def test_review_diff_returns_structured_response(self) -> None:
        """review_diff with mocked OpenAI returns parsed ReviewResponse."""
        reviewer = AIReviewer(api_key="test-key")
        mock_response = _make_openai_response(SAMPLE_REVIEW)

        with patch.object(
            reviewer._client.chat.completions, "create", return_value=mock_response
        ):
            result = reviewer.review_diff(
                file_path="src/main.py",
                patch="@@ -1 +1 @@\n-old\n+new",
                pr_title="Fix bug",
                pr_description="Fixes issue #1",
            )

        assert isinstance(result, ReviewResponse)
        assert len(result.comments) == 1
        assert result.comments[0].file_path == "src/main.py"
        assert result.comments[0].severity == "warning"
        assert result.comments[0].category == "bug"
        assert result.summary == "Found 1 issue."


class TestSystemPromptGenericWhenNoContext:
    """System prompt is generic when no project context is provided."""

    def test_generic_prompt_contains_review_keywords(self) -> None:
        reviewer = AIReviewer(api_key="test-key", project_context="")
        prompt = reviewer._build_system_prompt()

        assert "senior" in prompt.lower()
        assert "security" in prompt.lower() or "Security" in prompt
        assert "bug" in prompt.lower()
        assert "quant" not in prompt.lower()
        assert "trading" not in prompt.lower()


class TestSystemPromptContainsProjectContext:
    """System prompt includes project context when provided."""

    def test_prompt_includes_project_context(self) -> None:
        reviewer = AIReviewer(
            api_key="test-key",
            project_context="Django REST API for payments",
        )
        prompt = reviewer._build_system_prompt()

        assert "Django REST API for payments" in prompt


class TestBackwardCompatibleConstructor:
    """AIReviewer constructor works without project_context."""

    def test_no_type_error_without_project_context(self) -> None:
        reviewer = AIReviewer(api_key="test-key")
        prompt = reviewer._build_system_prompt()

        assert "senior" in prompt.lower()
        assert "quant" not in prompt.lower()


class TestSanitizeInputStripsMarkdown:
    """Test markdown stripping in _sanitize_input."""

    def test_sanitize_input_strips_markdown(self) -> None:
        """Bold, italic, links, headers, backticks stripped from input."""
        reviewer = AIReviewer(api_key="mock")

        assert reviewer._sanitize_input("**bold**") == "bold"
        assert reviewer._sanitize_input("*italic*") == "italic"
        assert reviewer._sanitize_input("[link](http://x.com)") == "link"
        assert reviewer._sanitize_input("# Header") == "Header"
        assert reviewer._sanitize_input("`code`") == "code"
        assert reviewer._sanitize_input("![alt](http://img.png)") == "alt"


class TestSanitizeInputTruncatesLongText:
    """Test that _sanitize_input caps text at MAX_INPUT_LENGTH."""

    def test_sanitize_input_truncates_long_text(self) -> None:
        """Input longer than 500 chars gets truncated to 500."""
        reviewer = AIReviewer(api_key="mock")
        long_text = "a" * 1000
        result = reviewer._sanitize_input(long_text)
        assert len(result) == 500


class TestReviewFilesAggregatesComments:
    """Test that review_files collects comments from multiple files."""

    def test_review_files_aggregates_comments(self) -> None:
        """review_files with 2 files returns combined comment list."""
        reviewer = AIReviewer(api_key="test-key")

        review_a = {
            "comments": [
                {
                    "file_path": "a.py",
                    "line_number": 1,
                    "severity": "error",
                    "category": "bug",
                    "comment": "Issue in a.py",
                }
            ],
            "summary": "Review of a.py",
        }
        review_b = {
            "comments": [
                {
                    "file_path": "b.py",
                    "line_number": 5,
                    "severity": "info",
                    "category": "readability",
                    "comment": "Issue in b.py",
                }
            ],
            "summary": "Review of b.py",
        }

        responses = [
            _make_openai_response(review_a),
            _make_openai_response(review_b),
        ]

        with patch.object(
            reviewer._client.chat.completions,
            "create",
            side_effect=responses,
        ):
            comments = reviewer.review_files(
                files=[
                    {"file_path": "a.py", "patch": "diff a"},
                    {"file_path": "b.py", "patch": "diff b"},
                ],
                pr_title="Multi-file PR",
                pr_description="Testing aggregation",
            )

        assert len(comments) == 2
        assert comments[0].file_path == "a.py"
        assert comments[1].file_path == "b.py"


class TestRateLimitRetries:
    """Test that rate limit errors trigger exponential backoff retries."""

    def test_rate_limit_retries(self) -> None:
        """RateLimitError retried up to MAX_RETRIES with backoff."""
        reviewer = AIReviewer(api_key="test-key")

        rate_limit_error = RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )

        with (
            patch.object(
                reviewer._client.chat.completions,
                "create",
                side_effect=rate_limit_error,
            ),
            patch("src.ai_reviewer.time.sleep") as mock_sleep,
        ):
            result = reviewer.review_diff(
                file_path="test.py",
                patch="diff",
                pr_title="Test",
                pr_description="Test",
            )

        assert result.summary.startswith("Error: Rate limit exceeded")
        assert mock_sleep.call_count == 2  # MAX_RETRIES - 1


class TestAuthErrorRaises:
    """Test that authentication errors are raised immediately."""

    def test_auth_error_raises(self) -> None:
        """AuthenticationError propagates without retry."""
        reviewer = AIReviewer(api_key="invalid-key")

        auth_error = AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401, headers={}),
            body=None,
        )

        with (
            patch.object(
                reviewer._client.chat.completions,
                "create",
                side_effect=auth_error,
            ),
            pytest.raises(AuthenticationError),
        ):
            reviewer.review_diff(
                file_path="test.py",
                patch="diff",
                pr_title="Test",
                pr_description="Test",
            )


class TestRefusalReturnsEmpty:
    """Test that model safety refusals return empty ReviewResponse."""

    def test_refusal_returns_empty(self) -> None:
        """Safety refusal returns ReviewResponse with no comments."""
        reviewer = AIReviewer(api_key="test-key")
        mock_response = _make_openai_response(
            content="",
            refusal="I cannot review this content.",
        )

        with patch.object(
            reviewer._client.chat.completions, "create", return_value=mock_response
        ):
            result = reviewer.review_diff(
                file_path="test.py",
                patch="diff",
                pr_title="Test",
                pr_description="Test",
            )

        assert isinstance(result, ReviewResponse)
        assert result.comments == []
        assert result.summary == ""


class TestMockModeWithoutApiKey:
    """Test mock mode returns canned response without API calls."""

    def test_mock_mode_without_api_key(self) -> None:
        """Empty API key triggers mock mode with canned response."""
        reviewer = AIReviewer(api_key="")
        assert reviewer._is_mock is True

        result = reviewer.review_diff(
            file_path="test.py",
            patch="diff",
            pr_title="Test",
            pr_description="Test",
        )

        assert isinstance(result, ReviewResponse)
        assert len(result.comments) == 1
        assert result.comments[0].file_path == "test.py"
        assert result.summary == "Mock review completed."

    def test_mock_mode_with_mock_key(self) -> None:
        """API key 'mock' triggers mock mode."""
        reviewer = AIReviewer(api_key="mock")
        assert reviewer._is_mock is True


class TestTokenTruncationHandled:
    """Test that token-truncated responses are handled gracefully."""

    def test_token_truncation_handled(self) -> None:
        """finish_reason='length' returns error ReviewResponse."""
        reviewer = AIReviewer(api_key="test-key")
        mock_response = _make_openai_response(
            content=json.dumps({"comments": [], "summary": "partial"}),
            finish_reason="length",
        )

        with patch.object(
            reviewer._client.chat.completions, "create", return_value=mock_response
        ):
            result = reviewer.review_diff(
                file_path="test.py",
                patch="diff",
                pr_title="Test",
                pr_description="Test",
            )

        assert isinstance(result, ReviewResponse)
        assert result.comments == []
        assert "truncated" in result.summary.lower()
